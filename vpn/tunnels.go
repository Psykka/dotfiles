package main

// Bringing each kind of VPN up as the link vpn0, without it touching the
// routes: routing.go decides what goes through it.
//
//	wireguard    configured straight through the kernel (no wg-quick)
//	openvpn      a child process with --route-noexec; its --up hook
//	             (`vpn hook openvpn`) tells the daemon the link is ready
//	openconnect  a child process whose --script (`vpn hook openconnect`)
//	             hands the daemon the addresses to give the link

import (
	"fmt"
	"net"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"golang.zx2c4.com/wireguard/wgctrl"
	"golang.zx2c4.com/wireguard/wgctrl/wgtypes"
)

// What a tunnel brings: its link is up and these are its settings.
type linkInfo struct {
	addrs  []string
	dns    []string
	routes []string // the networks it carries; 0.0.0.0/0 for the whole internet
	server string   // the VPN server's address: always reached the normal way
}

func wireguardUp(p *Profile) (*linkInfo, error) {
	text, err := os.ReadFile(p.file("config"))
	if err != nil {
		return nil, err
	}
	cfg, err := parseWireGuard(string(text))
	if err != nil {
		return nil, err
	}
	conf := wgtypes.Config{
		PrivateKey:   (*wgtypes.Key)(cfg.privateKey),
		FirewallMark: ptr(markBypass),
		ReplacePeers: true,
	}
	if cfg.listenPort > 0 {
		conf.ListenPort = ptr(cfg.listenPort)
	}
	for _, peer := range cfg.peers {
		pc := wgtypes.PeerConfig{PublicKey: wgtypes.Key(peer.publicKey), ReplaceAllowedIPs: true}
		if peer.presharedKey != nil {
			pc.PresharedKey = (*wgtypes.Key)(peer.presharedKey)
		}
		if peer.endpoint != "" {
			// The daemon's own lookups bypass the tunnel, so this works
			// even while the kill switch holds
			if pc.Endpoint, err = net.ResolveUDPAddr("udp", peer.endpoint); err != nil {
				return nil, fmt.Errorf("server %s: %v", peer.endpoint, err)
			}
		}
		if peer.keepalive > 0 {
			pc.PersistentKeepaliveInterval = ptr(time.Duration(peer.keepalive) * time.Second)
		}
		for _, a := range peer.allowedIPs {
			_, n, err := net.ParseCIDR(a)
			if err != nil {
				return nil, fmt.Errorf("AllowedIPs %q: %v", a, err)
			}
			pc.AllowedIPs = append(pc.AllowedIPs, *n)
		}
		conf.Peers = append(conf.Peers, pc)
	}

	deleteLink()
	if err := ip("link", "add", linkName, "type", "wireguard"); err != nil {
		return nil, err
	}
	wg, err := wgctrl.New()
	if err == nil {
		err = wg.ConfigureDevice(linkName, conf)
		wg.Close()
	}
	if err == nil {
		err = configureLink(cfg.addresses, cfg.mtu)
	}
	if err != nil {
		deleteLink()
		return nil, err
	}
	info := &linkInfo{addrs: cfg.addresses, dns: cfg.dns}
	for _, peer := range conf.Peers {
		for _, n := range peer.AllowedIPs {
			info.routes = append(info.routes, n.String())
		}
	}
	return info, nil
}

func ptr[T any](v T) *T { return &v }

// The server and the last handshake, for the panel
func wireguardStats() (endpoint string, handshake int64) {
	wg, err := wgctrl.New()
	if err != nil {
		return "", 0
	}
	defer wg.Close()
	dev, err := wg.Device(linkName)
	if err != nil || len(dev.Peers) == 0 {
		return "", 0
	}
	peer := dev.Peers[0]
	if peer.Endpoint != nil {
		endpoint = peer.Endpoint.String()
	}
	if !peer.LastHandshakeTime.IsZero() {
		handshake = peer.LastHandshakeTime.Unix()
	}
	return
}

// ------------------------------------------------------ child processes

// process is a running openvpn or openconnect. What it prints goes to the
// daemon's log, and the last lines are kept to tell why it failed.
type process struct {
	cmd  *exec.Cmd
	mu   sync.Mutex
	tail []string
	done chan struct{}
}

func (pr *process) Write(b []byte) (int, error) {
	pr.mu.Lock()
	defer pr.mu.Unlock()
	for _, line := range strings.Split(strings.TrimSpace(string(b)), "\n") {
		if line = strings.TrimSpace(line); line != "" {
			pr.tail = append(pr.tail, line)
		}
	}
	if len(pr.tail) > 30 {
		pr.tail = pr.tail[len(pr.tail)-30:]
	}
	os.Stderr.Write(b)
	return len(b), nil
}

func (pr *process) lines() []string {
	pr.mu.Lock()
	defer pr.mu.Unlock()
	return append([]string(nil), pr.tail...)
}

func (pr *process) stop() {
	if pr.cmd.Process == nil {
		return
	}
	pr.cmd.Process.Signal(syscall.SIGTERM)
	select {
	case <-pr.done:
	case <-time.After(3 * time.Second):
		pr.cmd.Process.Kill()
		<-pr.done
	}
}

func startProcess(stdin string, name string, args ...string) (*process, error) {
	pr := &process{cmd: exec.Command(name, args...), done: make(chan struct{})}
	pr.cmd.Stdout, pr.cmd.Stderr = pr, pr
	// Its scripts inherit the output pipes: don't wait on them for long
	// once it has quit
	pr.cmd.WaitDelay = 2 * time.Second
	if stdin != "" {
		pr.cmd.Stdin = strings.NewReader(stdin)
	}
	if err := pr.cmd.Start(); err != nil {
		return nil, err
	}
	go func() {
		pr.cmd.Wait()
		close(pr.done)
	}()
	return pr, nil
}

func self() string {
	exe, err := os.Executable()
	if err != nil {
		return "vpn"
	}
	return exe
}

func openvpnStart(p *Profile) (*process, error) {
	args := []string{"--config", p.file("config"),
		// After --config, so these win over the config
		"--dev", linkName, "--dev-type", "tun", "--route-noexec",
		// openvpn clears the environment of its scripts: the hook needs
		// to know where the daemon is
		"--script-security", "2", "--up", self() + " hook openvpn", "--setenv", "VPN_SOCKET", socketPath,
		"--pull-filter", "ignore", "block-outside-dns", "--verb", "3"}
	if p.Login {
		// openvpn reads the file more than once, so no pipe; it sits with
		// the password, in the profile's root-only folder
		auth := p.file("auth")
		if err := os.WriteFile(auth, []byte(p.Username+"\n"+p.secret()+"\n"), 0o600); err != nil {
			return nil, err
		}
		args = append(args, "--auth-user-pass", auth)
	}
	return startProcess("", "openvpn", args...)
}

// openvpnLink reads what openvpn's --up hook was given.
func openvpnLink(env map[string]string) *linkInfo {
	info := &linkInfo{server: env["trusted_ip"]}
	if info.server == "" {
		info.server = env["trusted_ip6"]
	}
	if a := env["ifconfig_local"]; a != "" {
		info.addrs = append(info.addrs, a)
	}
	if a := env["ifconfig_ipv6_local"]; a != "" {
		info.addrs = append(info.addrs, a)
	}
	// The routes it was told to add (--route-noexec keeps it from adding them)
	if env["route_redirect_gateway_ipv4"] != "" {
		info.routes = append(info.routes, "0.0.0.0/0")
	}
	if env["route_redirect_gateway_ipv6"] != "" {
		info.routes = append(info.routes, "::/0")
	}
	for i := 1; ; i++ {
		network, ok := env[fmt.Sprintf("route_network_%d", i)]
		if !ok {
			break
		}
		if mask := net.ParseIP(env[fmt.Sprintf("route_netmask_%d", i)]).To4(); mask != nil {
			ones, _ := net.IPMask(mask).Size()
			info.routes = append(info.routes, fmt.Sprintf("%s/%d", network, ones))
		}
	}
	for i := 1; ; i++ {
		network, ok := env[fmt.Sprintf("route_ipv6_network_%d", i)]
		if !ok {
			break
		}
		info.routes = append(info.routes, network)
	}
	// Pushed options: foreign_option_1="dhcp-option DNS 10.8.0.1"
	for i := 1; ; i++ {
		opt, ok := env[fmt.Sprintf("foreign_option_%d", i)]
		if !ok {
			break
		}
		f := strings.Fields(opt)
		if len(f) == 3 && f[0] == "dhcp-option" && (f[1] == "DNS" || f[1] == "DNS6") && net.ParseIP(f[2]) != nil {
			info.dns = append(info.dns, f[2])
		}
	}
	return info
}

func openconnectStart(p *Profile) (*process, error) {
	args := []string{"--protocol=" + p.Protocol, "--interface=" + linkName, "--non-inter",
		"--script=" + self() + " hook openconnect"}
	if p.ServerCert != "" {
		args = append(args, "--servercert="+p.ServerCert)
	}
	stdin := ""
	if p.Username != "" {
		args = append(args, "--user="+p.Username)
	}
	if pw := p.secret(); pw != "" {
		args = append(args, "--passwd-on-stdin")
		stdin = pw + "\n"
	}
	return startProcess(stdin, "openconnect", append(args, p.Server)...)
}

// openconnectLink gives vpn0 the addresses openconnect's script was handed
// (the vpnc-script variables) and brings it up.
func openconnectLink(env map[string]string) (*linkInfo, error) {
	info := &linkInfo{server: env["VPNGATEWAY"]}
	if a := env["INTERNAL_IP4_ADDRESS"]; a != "" {
		info.addrs = append(info.addrs, a+"/32")
	}
	if a := env["INTERNAL_IP6_NETMASK"]; strings.Contains(a, "/") {
		info.addrs = append(info.addrs, a)
	} else if a := env["INTERNAL_IP6_ADDRESS"]; a != "" {
		info.addrs = append(info.addrs, a+"/128")
	}
	for _, k := range []string{"INTERNAL_IP4_DNS", "INTERNAL_IP6_DNS"} {
		for _, d := range strings.Fields(env[k]) {
			if net.ParseIP(d) != nil {
				info.dns = append(info.dns, d)
			}
		}
	}
	// Split routes, when the server sends some; the whole internet otherwise
	for _, family := range []string{"CISCO_SPLIT_INC", "CISCO_IPV6_SPLIT_INC"} {
		n, _ := strconv.Atoi(env[family])
		for i := 0; i < n; i++ {
			addr, bits := env[fmt.Sprintf("%s_%d_ADDR", family, i)], env[fmt.Sprintf("%s_%d_MASKLEN", family, i)]
			if addr != "" && bits != "" {
				info.routes = append(info.routes, addr+"/"+bits)
			}
		}
	}
	if len(info.routes) == 0 {
		info.routes = []string{"0.0.0.0/0"}
		if env["INTERNAL_IP6_ADDRESS"] != "" || env["INTERNAL_IP6_NETMASK"] != "" {
			info.routes = append(info.routes, "::/0")
		}
	}
	mtu := 0
	fmt.Sscan(env["INTERNAL_IP4_MTU"], &mtu)
	err := configureLink(info.addrs, mtu)
	return info, err
}
