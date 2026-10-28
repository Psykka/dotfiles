package main

// The daemon (`vpn daemon`, vpnd.service, root): one VPN at a time, as the
// link vpn0. Clients talk to it on a unix socket, one JSON request per
// connection; it answers to root and to the users in /etc/vpn/users.
//
// States: off -> connecting -> on. A VPN that fails to connect goes to
// "failed" and leaves nothing behind; one that drops after connecting goes
// to "dropped" and keeps its rules, so the traffic meant for it is cut
// (kill switch) until `vpn up` or `vpn down`.

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"os/user"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

var (
	socketPath = envOr("VPN_SOCKET", "/run/vpn/vpnd.sock")
	usersFile  = envOr("VPN_USERS", "/etc/vpn/users")
)

// Used when a VPN out to the internet doesn't say which DNS servers to use;
// asked through the tunnel. One into some networks just leaves DNS alone.
var fallbackDNS = []string{"1.1.1.1", "1.0.0.1"}

type Request struct {
	Cmd     string            `json:"cmd"`
	Profile string            `json:"profile,omitempty"`
	Mode    string            `json:"mode,omitempty"`
	Import  *ImportRequest    `json:"import,omitempty"`
	Kind    string            `json:"kind,omitempty"`
	Env     map[string]string `json:"env,omitempty"`
}

type Response struct {
	Error  string  `json:"error,omitempty"`
	Status *Status `json:"status,omitempty"`
}

type App struct {
	Name string `json:"name"`
	Pids []int  `json:"pids"`
}

type Status struct {
	State     string    `json:"state"` // off | connecting | on | dropped | failed
	Profile   string    `json:"profile"`
	Kind      string    `json:"kind"`
	Mode      string    `json:"mode"` // full | apps
	Error     string    `json:"error"`
	Since     int64     `json:"since"`
	Addresses []string  `json:"addresses"`
	Routes    []string  `json:"routes"` // the networks it carries
	DNS       []string  `json:"dns"`
	Endpoint  string    `json:"endpoint"`
	Handshake int64     `json:"handshake"`
	Rx        uint64    `json:"rx"`
	Tx        uint64    `json:"tx"`
	Last      string    `json:"last"` // what `vpn up` with no name connects to
	Profiles  []Profile `json:"profiles"`
	Apps      []App     `json:"apps"` // the asking user's apps in the tunnel
}

// What survives a restart
type saved struct {
	Mode string `json:"mode"`
	Last string `json:"last"`
}

type daemon struct {
	mu       sync.Mutex
	gen      int // bumped on every up/down, so late events of an old VPN are dropped
	state    string
	profile  *Profile
	uid      int
	err      string
	since    time.Time
	proc     *process
	link     *linkInfo
	saved    saved
	dns      forwarder
	watchers map[chan struct{}]bool
}

func runDaemon() {
	d := &daemon{state: "off", saved: saved{Mode: "full"}, watchers: map[chan struct{}]bool{}}
	if data, err := os.ReadFile(filepath.Join(stateDir, "state.json")); err == nil {
		json.Unmarshal(data, &d.saved)
	}
	// Leftovers of a daemon that didn't stop cleanly
	removeRouting()
	deleteLink()

	if err := d.dns.serve(); err != nil {
		log.Fatalf("dns forwarder: %v", err)
	}
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		<-stop
		d.mu.Lock()
		d.stopLocked()
		os.Remove(socketPath)
		os.Exit(0)
	}()
	if err := d.serve(); err != nil {
		log.Fatal(err)
	}
}

func (d *daemon) save() {
	os.MkdirAll(stateDir, 0o700)
	data, _ := json.Marshal(d.saved)
	os.WriteFile(filepath.Join(stateDir, "state.json"), data, 0o600)
}

func (d *daemon) changed() {
	for ch := range d.watchers {
		select {
		case ch <- struct{}{}:
		default:
		}
	}
}

// ------------------------------------------------------------- the VPN

func (d *daemon) up(name string, uid int) error {
	p, err := loadProfile(name)
	if err != nil {
		return err
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	d.stopLocked()
	gen := d.gen
	d.profile, d.uid, d.state, d.err, d.since = p, uid, "connecting", "", time.Now()
	d.saved.Last = name
	d.save()
	d.changed()

	switch p.Kind {
	case "wireguard":
		// Resolving the server can take a while: not under the lock
		go func() {
			link, err := wireguardUp(p)
			d.mu.Lock()
			defer d.mu.Unlock()
			if gen != d.gen {
				return
			}
			if err == nil {
				err = d.connectedLocked(link)
			}
			if err != nil {
				d.failLocked(err.Error())
			}
		}()
		return nil
	case "openvpn":
		d.proc, err = openvpnStart(p)
	case "openconnect":
		d.proc, err = openconnectStart(p)
	default:
		err = fmt.Errorf("unknown kind %q", p.Kind)
	}
	if err != nil {
		d.failLocked(err.Error())
		return err
	}
	go func(pr *process) {
		<-pr.done
		d.exited(gen, pr)
	}(d.proc)
	return nil
}

// connectedLocked routes the traffic through the link that just came up.
func (d *daemon) connectedLocked(link *linkInfo) error {
	servers := link.dns
	if len(servers) == 0 && gateway(link.routes) {
		servers = fallbackDNS
	}
	if err := installRouting(d.saved.Mode, d.uid, link, len(servers) > 0); err != nil {
		return err
	}
	d.link = link
	d.dns.set(servers)
	d.state, d.since = "on", time.Now()
	d.changed()
	return nil
}

func (d *daemon) failLocked(msg string) {
	d.stopLocked()
	d.state, d.err = "failed", msg
	d.changed()
}

// stopLocked takes everything down: the VPN, its link and the rules.
func (d *daemon) stopLocked() {
	d.gen++
	if d.proc != nil {
		d.proc.stop()
		d.proc = nil
	}
	removeRouting()
	deleteLink()
	d.dns.set(nil)
	d.state, d.err, d.link = "off", "", nil
}

func (d *daemon) down() {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.stopLocked()
	d.changed()
}

// exited: openvpn or openconnect quit (wrong password, server gone...).
func (d *daemon) exited(gen int, pr *process) {
	d.mu.Lock()
	defer d.mu.Unlock()
	if gen != d.gen {
		return
	}
	d.proc = nil
	reason := why(pr.lines())
	if d.state == "on" {
		// Rules stay: what went through the VPN is cut, not leaked
		d.state, d.err = "dropped", reason
		d.dns.set(nil)
		d.changed()
		return
	}
	d.failLocked(reason)
}

// why picks the line that best tells why a VPN quit: the most telling
// words first, the latest line with them.
func why(lines []string) string {
	keys := []string{"AUTH_FAILED", "Login failed", "auth", "Auth", "refused", "Cannot", "annot ",
		"nable to", "rror", "fail", "Fail"}
	for _, k := range keys {
		for i := len(lines) - 1; i >= 0; i-- {
			if strings.Contains(lines[i], k) {
				return lines[i]
			}
		}
	}
	if len(lines) > 0 {
		return lines[len(lines)-1]
	}
	return "the VPN quit"
}

// hook: openvpn's --up or openconnect's --script, run by the VPN itself.
func (d *daemon) hook(kind string, env map[string]string) error {
	// openconnect's other reasons (pre-init, disconnect, reconnect...) need
	// nothing: the link and the rules outlive a reconnect. Answered before
	// taking the lock: on `vpn down` the lock is held while openconnect
	// quits, and it runs this hook (disconnect) on its way out
	if kind == "openconnect" && env["reason"] != "connect" {
		return nil
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.proc == nil || d.profile == nil || d.profile.Kind != kind {
		return errors.New("no such VPN starting")
	}
	var link *linkInfo
	var err error
	switch kind {
	case "openvpn":
		link = openvpnLink(env)
	case "openconnect":
		if link, err = openconnectLink(env); err != nil {
			return err
		}
	}
	return d.connectedLocked(link)
}

func (d *daemon) setMode(mode string) error {
	if mode != "full" && mode != "apps" {
		return errors.New("mode: full or apps")
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	d.saved.Mode = mode
	d.save()
	if d.state == "on" {
		if err := installRouting(mode, d.uid, d.link, len(d.dns.upstream()) > 0); err != nil {
			d.failLocked(err.Error())
			return err
		}
	}
	d.changed()
	return nil
}

func (d *daemon) status(uid int) *Status {
	d.mu.Lock()
	s := &Status{State: d.state, Mode: d.saved.Mode, Error: d.err, Last: d.saved.Last,
		Addresses: []string{}, Routes: []string{}, DNS: []string{}}
	if d.profile != nil {
		s.Profile, s.Kind = d.profile.Name, d.profile.Kind
		s.Since = d.since.Unix()
	}
	if d.link != nil {
		s.Addresses, s.Routes = d.link.addrs, d.link.routes
		s.DNS = append(s.DNS, d.dns.upstream()...)
	}
	on := d.state == "on"
	d.mu.Unlock()

	if on {
		s.Rx, s.Tx = linkStats()
		if s.Kind == "wireguard" {
			s.Endpoint, s.Handshake = wireguardStats()
		}
	}
	s.Profiles = listProfiles()
	s.Apps = sliceApps(uid)
	return s
}

// sliceApps lists the processes of the user's vpn.slice (what `vpn run`
// started), but not the anchor that keeps the slice alive.
func sliceApps(uid int) []App {
	byName := map[string][]int{}
	root := filepath.Join("/sys/fs/cgroup", slicePath(uid))
	filepath.WalkDir(root, func(path string, e os.DirEntry, err error) error {
		if err != nil || e.Name() != "cgroup.procs" || strings.Contains(path, "vpn-anchor") {
			return nil
		}
		data, _ := os.ReadFile(path)
		for _, f := range strings.Fields(string(data)) {
			pid, _ := strconv.Atoi(f)
			comm, err := os.ReadFile(fmt.Sprintf("/proc/%d/comm", pid))
			if err == nil {
				name := strings.TrimSpace(string(comm))
				byName[name] = append(byName[name], pid)
			}
		}
		return nil
	})
	apps := []App{}
	for name, pids := range byName {
		apps = append(apps, App{name, pids})
	}
	sort.Slice(apps, func(i, j int) bool { return apps[i].Name < apps[j].Name })
	return apps
}

// ------------------------------------------------------------- the socket

func (d *daemon) serve() error {
	os.MkdirAll(filepath.Dir(socketPath), 0o755)
	os.Remove(socketPath)
	ln, err := net.Listen("unix", socketPath)
	if err != nil {
		return err
	}
	// Anyone may connect; who may do what is checked per request
	os.Chmod(socketPath, 0o666)
	for {
		conn, err := ln.Accept()
		if err != nil {
			return err
		}
		go d.handle(conn.(*net.UnixConn))
	}
}

func peerUID(c *net.UnixConn) (int, error) {
	raw, err := c.SyscallConn()
	if err != nil {
		return -1, err
	}
	var cred *syscall.Ucred
	raw.Control(func(fd uintptr) {
		cred, err = syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
	})
	if err != nil {
		return -1, err
	}
	return int(cred.Uid), nil
}

// The users allowed to control the VPN: names or uids, one per line.
func allowedUsers() []int {
	data, _ := os.ReadFile(usersFile)
	var uids []int
	for _, line := range strings.Fields(string(data)) {
		if uid, err := strconv.Atoi(line); err == nil {
			uids = append(uids, uid)
		} else if u, err := user.Lookup(line); err == nil {
			uid, _ := strconv.Atoi(u.Uid)
			uids = append(uids, uid)
		}
	}
	return uids
}

func (d *daemon) handle(conn *net.UnixConn) {
	defer conn.Close()
	uid, err := peerUID(conn)
	if err != nil {
		return
	}
	var req Request
	if err := json.NewDecoder(bufio.NewReader(conn)).Decode(&req); err != nil {
		return
	}
	enc := json.NewEncoder(conn)
	users := allowedUsers()
	allowed := uid == 0
	for _, u := range users {
		allowed = allowed || u == uid
	}
	if !allowed {
		enc.Encode(Response{Error: "not allowed: add your user to " + usersFile})
		return
	}
	// root (sudo vpn ...) acts for the first user: it is their slice
	root := uid == 0
	if root && len(users) > 0 {
		uid = users[0]
	}

	switch req.Cmd {
	case "status":
		enc.Encode(Response{Status: d.status(uid)})
	case "watch":
		d.watch(conn, enc, uid)
	default:
		err := d.command(req, uid, root)
		if err != nil {
			enc.Encode(Response{Error: err.Error()})
		} else {
			enc.Encode(Response{Status: d.status(uid)})
		}
	}
}

func (d *daemon) command(req Request, uid int, root bool) error {
	switch req.Cmd {
	case "up":
		name := req.Profile
		if name == "" {
			d.mu.Lock()
			name = d.saved.Last
			d.mu.Unlock()
		}
		if name == "" {
			return errors.New("which VPN? (vpn list)")
		}
		return d.up(name, uid)
	case "down":
		d.down()
	case "mode":
		return d.setMode(req.Mode)
	case "import":
		if req.Import == nil {
			return errors.New("nothing to import")
		}
		if _, err := importProfile(*req.Import); err != nil {
			return err
		}
		d.mu.Lock()
		d.changed()
		d.mu.Unlock()
	case "remove":
		d.mu.Lock()
		active := d.profile != nil && d.profile.Name == req.Profile && d.state != "off"
		if d.saved.Last == req.Profile {
			d.saved.Last = ""
			d.save()
		}
		d.mu.Unlock()
		if active {
			d.down()
		}
		if err := removeProfile(req.Profile); err != nil {
			return err
		}
		d.mu.Lock()
		d.changed()
		d.mu.Unlock()
	case "hook":
		// Only the VPN the daemon started (root) may say it is ready
		if !root {
			return errors.New("not allowed")
		}
		return d.hook(req.Kind, req.Env)
	default:
		return fmt.Errorf("unknown command %q", req.Cmd)
	}
	return nil
}

// watch sends the status now and again on every change, until the client
// goes away.
func (d *daemon) watch(conn net.Conn, enc *json.Encoder, uid int) {
	ch := make(chan struct{}, 1)
	d.mu.Lock()
	d.watchers[ch] = true
	d.mu.Unlock()
	defer func() {
		d.mu.Lock()
		delete(d.watchers, ch)
		d.mu.Unlock()
	}()
	gone := make(chan struct{})
	go func() {
		buf := make([]byte, 1)
		conn.Read(buf)
		close(gone)
	}()
	for {
		if enc.Encode(Response{Status: d.status(uid)}) != nil {
			return
		}
		select {
		case <-ch:
		case <-gone:
			return
		}
	}
}
