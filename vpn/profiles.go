package main

// Profiles: the VPNs that were imported, one folder each under
// /var/lib/vpn/profiles (root only, they hold keys and passwords):
//
//	profile.json   name, kind and what the panel shows
//	config         the WireGuard .conf or the OpenVPN .ovpn, as imported
//	secret         the password, for OpenVPN and OpenConnect logins
//	auth           OpenVPN's login file, written on connect

import (
	"bufio"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

type Profile struct {
	Name       string `json:"name"`
	Kind       string `json:"kind"`             // wireguard | openvpn | openconnect
	Server     string `json:"server,omitempty"` // host shown in the panel
	Protocol   string `json:"protocol,omitempty"`
	Username   string `json:"username,omitempty"`
	ServerCert string `json:"servercert,omitempty"`
	// OpenVPN asks for a login (auth-user-pass)
	Login bool `json:"login,omitempty"`
}

// The request to add a profile. Text is the file's content (WireGuard or
// OpenVPN, told apart by it); OpenConnect has no file, just the server.
type ImportRequest struct {
	Name       string `json:"name"`
	Text       string `json:"text,omitempty"`
	Kind       string `json:"kind,omitempty"`
	Server     string `json:"server,omitempty"`
	Protocol   string `json:"protocol,omitempty"`
	Username   string `json:"username,omitempty"`
	Password   string `json:"password,omitempty"`
	ServerCert string `json:"servercert,omitempty"`
}

var stateDir = envOr("VPN_STATE_DIR", "/var/lib/vpn")

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func profileDir(name string) string { return filepath.Join(stateDir, "profiles", name) }

var validName = regexp.MustCompile(`^[\w][\w .+-]{0,31}$`)

// The protocols openconnect speaks, by its --protocol name
var protocols = map[string]bool{"anyconnect": true, "gp": true, "fortinet": true, "pulse": true,
	"nc": true, "f5": true, "array": true}

func loadProfile(name string) (*Profile, error) {
	data, err := os.ReadFile(filepath.Join(profileDir(name), "profile.json"))
	if err != nil {
		return nil, fmt.Errorf("no VPN named %q", name)
	}
	var p Profile
	return &p, json.Unmarshal(data, &p)
}

func listProfiles() []Profile {
	entries, _ := os.ReadDir(filepath.Join(stateDir, "profiles"))
	out := []Profile{}
	for _, e := range entries {
		if p, err := loadProfile(e.Name()); err == nil {
			out = append(out, *p)
		}
	}
	sort.Slice(out, func(i, j int) bool { return strings.ToLower(out[i].Name) < strings.ToLower(out[j].Name) })
	return out
}

func (p *Profile) file(name string) string { return filepath.Join(profileDir(p.Name), name) }

func (p *Profile) secret() string {
	data, _ := os.ReadFile(p.file("secret"))
	return string(data)
}

// importProfile checks and stores a new profile.
func importProfile(req ImportRequest) (*Profile, error) {
	req.Name = strings.TrimSpace(req.Name)
	if !validName.MatchString(req.Name) {
		return nil, errors.New("name: up to 32 letters, digits, spaces, '.', '+' or '-'")
	}
	if _, err := os.Stat(profileDir(req.Name)); err == nil {
		return nil, fmt.Errorf("there is already a VPN named %q", req.Name)
	}
	p := &Profile{Name: req.Name, Username: req.Username}
	switch {
	case req.Kind == "openconnect":
		p.Kind, p.Server, p.Protocol, p.ServerCert = "openconnect", strings.TrimSpace(req.Server), req.Protocol, req.ServerCert
		if p.Server == "" {
			return nil, errors.New("the server is missing")
		}
		if p.Protocol == "" {
			p.Protocol = "anyconnect"
		}
		if !protocols[p.Protocol] {
			return nil, fmt.Errorf("unknown protocol %q", p.Protocol)
		}
	case strings.Contains(req.Text, "[Interface]"):
		cfg, err := parseWireGuard(req.Text)
		if err != nil {
			return nil, err
		}
		p.Kind = "wireguard"
		if len(cfg.peers) > 0 {
			p.Server = hostOf(cfg.peers[0].endpoint)
		}
	default:
		info, err := checkOpenVPN(req.Text)
		if err != nil {
			return nil, err
		}
		p.Kind, p.Server, p.Login = "openvpn", info.server, info.login
		if p.Login && (req.Username == "" || req.Password == "") {
			return nil, errors.New("this OpenVPN config asks for a username and password")
		}
	}

	dir := profileDir(p.Name)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	data, _ := json.MarshalIndent(p, "", "  ")
	err := os.WriteFile(filepath.Join(dir, "profile.json"), append(data, '\n'), 0o600)
	if err == nil && req.Text != "" {
		err = os.WriteFile(filepath.Join(dir, "config"), []byte(req.Text), 0o600)
	}
	if err == nil && req.Password != "" {
		err = os.WriteFile(filepath.Join(dir, "secret"), []byte(req.Password), 0o600)
	}
	if err != nil {
		os.RemoveAll(dir)
		return nil, err
	}
	return p, nil
}

func removeProfile(name string) error {
	if _, err := loadProfile(name); err != nil {
		return err
	}
	return os.RemoveAll(profileDir(name))
}

func hostOf(endpoint string) string {
	if host, _, err := net.SplitHostPort(endpoint); err == nil {
		return host
	}
	return endpoint
}

// ------------------------------------------------------------ WireGuard

type wgPeer struct {
	publicKey, presharedKey []byte
	allowedIPs              []string
	endpoint                string
	keepalive               int
}

type wgConfig struct {
	privateKey []byte
	listenPort int
	addresses  []string
	dns        []string
	mtu        int
	peers      []wgPeer
}

func wgKey(value string) ([]byte, error) {
	key, err := base64.StdEncoding.DecodeString(value)
	if err != nil || len(key) != 32 {
		return nil, fmt.Errorf("invalid key %q", value)
	}
	return key, nil
}

func splitList(value string) []string {
	var out []string
	for _, v := range strings.Split(value, ",") {
		if v = strings.TrimSpace(v); v != "" {
			out = append(out, v)
		}
	}
	return out
}

// parseWireGuard reads a wg-quick style config. PreUp/PostUp and the like
// are ignored: nothing in a config runs as root.
func parseWireGuard(text string) (*wgConfig, error) {
	cfg := &wgConfig{}
	section := ""
	sc := bufio.NewScanner(strings.NewReader(text))
	for n := 1; sc.Scan(); n++ {
		line, _, _ := strings.Cut(sc.Text(), "#")
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "[") {
			section = strings.ToLower(strings.Trim(line, "[] "))
			if section == "peer" {
				cfg.peers = append(cfg.peers, wgPeer{})
			}
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			return nil, fmt.Errorf("line %d: expected key = value", n)
		}
		key, value = strings.ToLower(strings.TrimSpace(key)), strings.TrimSpace(value)
		var err error
		switch section + "." + key {
		case "interface.privatekey":
			cfg.privateKey, err = wgKey(value)
		case "interface.listenport":
			cfg.listenPort, err = strconv.Atoi(value)
		case "interface.address":
			for _, a := range splitList(value) {
				if _, _, e := net.ParseCIDR(a); e != nil {
					if net.ParseIP(a) == nil {
						return nil, fmt.Errorf("line %d: invalid address %q", n, a)
					}
					if strings.Contains(a, ":") {
						a += "/128"
					} else {
						a += "/32"
					}
				}
				cfg.addresses = append(cfg.addresses, a)
			}
		case "interface.dns":
			// Search domains are left out: just the servers
			for _, d := range splitList(value) {
				if net.ParseIP(d) != nil {
					cfg.dns = append(cfg.dns, d)
				}
			}
		case "interface.mtu":
			cfg.mtu, err = strconv.Atoi(value)
		case "peer.publickey":
			cfg.peers[len(cfg.peers)-1].publicKey, err = wgKey(value)
		case "peer.presharedkey":
			cfg.peers[len(cfg.peers)-1].presharedKey, err = wgKey(value)
		case "peer.allowedips":
			cfg.peers[len(cfg.peers)-1].allowedIPs = splitList(value)
		case "peer.endpoint":
			cfg.peers[len(cfg.peers)-1].endpoint = value
		case "peer.persistentkeepalive":
			if value != "off" {
				cfg.peers[len(cfg.peers)-1].keepalive, err = strconv.Atoi(value)
			}
		}
		if err != nil {
			return nil, fmt.Errorf("line %d: %v", n, err)
		}
	}
	switch {
	case cfg.privateKey == nil:
		return nil, errors.New("WireGuard config without PrivateKey")
	case len(cfg.addresses) == 0:
		return nil, errors.New("WireGuard config without Address")
	case len(cfg.peers) == 0:
		return nil, errors.New("WireGuard config without [Peer]")
	}
	for _, p := range cfg.peers {
		if p.publicKey == nil {
			return nil, errors.New("[Peer] without PublicKey")
		}
	}
	return cfg, nil
}

// --------------------------------------------------------------- OpenVPN

type ovpnInfo struct {
	server string
	login  bool
}

// Options that run commands, write files or replace what the daemon sets
// (the link, the routes, the login): an imported config may not have them,
// since openvpn runs as root.
var ovpnForbidden = map[string]bool{
	"script-security": true, "up": true, "down": true, "route-up": true, "route-pre-down": true,
	"ipchange": true, "tls-verify": true, "learn-address": true, "client-connect": true,
	"client-disconnect": true, "auth-user-pass-verify": true, "plugin": true, "management": true,
	"log": true, "log-append": true, "writepid": true, "status": true, "cd": true, "chroot": true,
	"config": true, "daemon": true, "user": true, "group": true, "dev-node": true, "iproute": true,
	"setenv": true, "setenv-safe": true, "tmp-dir": true, "askpass": true, "echo": true,
}

// Options that read a file, unless the content is inline (<ca>...</ca>)
var ovpnFiles = map[string]bool{
	"ca": true, "cert": true, "key": true, "tls-auth": true, "tls-crypt": true, "tls-crypt-v2": true,
	"pkcs12": true, "secret": true, "crl-verify": true, "dh": true, "extra-certs": true,
	"http-proxy-user-pass": true,
}

func checkOpenVPN(text string) (*ovpnInfo, error) {
	info := &ovpnInfo{}
	inline := map[string]bool{}
	type ref struct {
		option string
		line   int
	}
	var files []ref
	block, client := "", false
	sc := bufio.NewScanner(strings.NewReader(text))
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	for n := 1; sc.Scan(); n++ {
		line := strings.TrimSpace(sc.Text())
		if block != "" {
			if line == "</"+block+">" {
				block = ""
			}
			continue
		}
		if strings.HasPrefix(line, "<") && strings.HasSuffix(line, ">") && !strings.HasPrefix(line, "</") {
			block = strings.Trim(line, "<>")
			inline[block] = true
			continue
		}
		if line == "" || line[0] == '#' || line[0] == ';' {
			continue
		}
		fields := strings.Fields(line)
		option := strings.TrimPrefix(fields[0], "--")
		switch {
		case ovpnForbidden[option]:
			return nil, fmt.Errorf("line %d: the option %q is not allowed (it would run as root)", n, option)
		case option == "client" || option == "tls-client" || option == "pull":
			client = true
		case option == "remote" && len(fields) > 1 && info.server == "":
			info.server = fields[1]
		case option == "dev" && len(fields) > 1 && strings.HasPrefix(fields[1], "tap"):
			return nil, errors.New("tap configs are not supported, only tun")
		case option == "auth-user-pass":
			if len(fields) > 1 {
				return nil, fmt.Errorf("line %d: auth-user-pass reads a file; remove the file name and type the login here", n)
			}
			info.login = true
		case ovpnFiles[option] && len(fields) > 1 && fields[1] != "[inline]":
			files = append(files, ref{option, n})
		}
	}
	for _, f := range files {
		if !inline[f.option] {
			return nil, fmt.Errorf("line %d: %q points at a separate file; use a config with it inline (<%s>...</%s>)",
				f.line, f.option, f.option, f.option)
		}
	}
	if !client || info.server == "" {
		return nil, errors.New("not a WireGuard or OpenVPN client config")
	}
	return info, nil
}
