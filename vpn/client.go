package main

// The client side: terminal commands, the bar's status and the hooks the
// VPNs run. Everything goes through the daemon's socket, except starting
// apps in the slice, which is the user's own systemd.

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

func dial() (net.Conn, error) {
	conn, err := net.Dial("unix", socketPath)
	if err != nil {
		return nil, errors.New("the VPN daemon is not running (systemctl start vpnd)")
	}
	return conn, nil
}

func call(req Request) (*Status, error) {
	conn, err := dial()
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	if err := json.NewEncoder(conn).Encode(req); err != nil {
		return nil, err
	}
	var resp Response
	if err := json.NewDecoder(conn).Decode(&resp); err != nil {
		return nil, fmt.Errorf("no answer from the daemon: %v", err)
	}
	if resp.Error != "" {
		return nil, errors.New(resp.Error)
	}
	return resp.Status, nil
}

// watch calls fn with the status now and on every change, until fn
// returns false, the daemon goes away or the deadline (if any) passes.
func watch(deadline time.Time, fn func(*Status) bool) error {
	conn, err := dial()
	if err != nil {
		return err
	}
	defer conn.Close()
	conn.SetDeadline(deadline)
	json.NewEncoder(conn).Encode(Request{Cmd: "watch"})
	dec := json.NewDecoder(conn)
	for {
		var resp Response
		if err := dec.Decode(&resp); err != nil {
			if errors.Is(err, os.ErrDeadlineExceeded) {
				return err
			}
			return errors.New("the VPN daemon went away")
		}
		if resp.Status != nil && !fn(resp.Status) {
			return nil
		}
	}
}

func size(n uint64) string {
	units := []string{"B", "KiB", "MiB", "GiB", "TiB"}
	f, i := float64(n), 0
	for f >= 1024 && i < len(units)-1 {
		f /= 1024
		i++
	}
	if i == 0 {
		return fmt.Sprintf("%d B", n)
	}
	return fmt.Sprintf("%.1f %s", f, units[i])
}

func cliStatus(asJSON bool) error {
	s, err := call(Request{Cmd: "status"})
	if err != nil {
		return err
	}
	if asJSON {
		return json.NewEncoder(os.Stdout).Encode(s)
	}
	mode := map[string]string{"full": "the whole system uses the VPN", "apps": "only apps started with `vpn run` use it"}[s.Mode]
	switch s.State {
	case "off":
		fmt.Println("off")
	case "failed":
		fmt.Printf("%s failed: %s\n", s.Profile, s.Error)
	case "dropped":
		fmt.Printf("%s dropped: %s\n  its traffic stays cut until `vpn up` or `vpn down`\n", s.Profile, s.Error)
	default:
		fmt.Printf("%s: %s (%s)\n", s.Profile, s.State, s.Kind)
	}
	if s.State == "on" {
		dns := strings.Join(s.DNS, " ")
		if dns == "" {
			dns = "the normal one (the VPN has none)"
		}
		fmt.Printf("  address    %s\n  networks   %s\n  dns        %s\n  traffic    %s in, %s out\n",
			strings.Join(s.Addresses, " "), strings.Join(s.Routes, " "), dns, size(s.Rx), size(s.Tx))
		if s.Endpoint != "" {
			fmt.Printf("  server     %s\n", s.Endpoint)
		}
	}
	fmt.Printf("mode: %s (%s)\n", s.Mode, mode)
	if len(s.Apps) > 0 {
		fmt.Println("apps in the VPN:")
		for _, a := range s.Apps {
			fmt.Printf("  %-20s %d\n", a.Name, a.Pids)
		}
	}
	return nil
}

func cliList() error {
	s, err := call(Request{Cmd: "status"})
	if err != nil {
		return err
	}
	for _, p := range s.Profiles {
		mark := " "
		if p.Name == s.Profile && s.State != "off" {
			mark = "*"
		}
		fmt.Printf("%s %-24s %-12s %s\n", mark, p.Name, p.Kind, p.Server)
	}
	return nil
}

// cliUp connects and waits until it is on (or failed).
func cliUp(name string) error {
	s, err := call(Request{Cmd: "up", Profile: name})
	if err != nil {
		return err
	}
	name = s.Profile
	var result error
	err = watch(time.Now().Add(60*time.Second), func(s *Status) bool {
		switch {
		case s.Profile != name:
			result = errors.New("another VPN was started meanwhile")
		case s.State == "on":
			fmt.Printf("%s: on\n", name)
		case s.State == "failed":
			result = fmt.Errorf("%s: %s", name, s.Error)
		default:
			return true
		}
		return false
	})
	if errors.Is(err, os.ErrDeadlineExceeded) {
		return fmt.Errorf("%s: still connecting after a minute (it goes on; `vpn down` stops it)", name)
	}
	if err != nil {
		return err
	}
	return result
}

func cliToggle(name string) error {
	s, err := call(Request{Cmd: "status"})
	if err != nil {
		return err
	}
	if s.State != "off" && s.State != "failed" && (name == "" || name == s.Profile) {
		_, err = call(Request{Cmd: "down"})
		return err
	}
	_, err = call(Request{Cmd: "up", Profile: name})
	return err
}

func cliMode(mode string) error {
	if mode == "" {
		s, err := call(Request{Cmd: "status"})
		if err == nil {
			fmt.Println(s.Mode)
		}
		return err
	}
	_, err := call(Request{Cmd: "mode", Mode: mode})
	return err
}

// flags pulls --key VALUE pairs out of args; the rest stay in order.
func flags(args []string, names ...string) (map[string]string, []string) {
	out, rest := map[string]string{}, []string{}
	for i := 0; i < len(args); i++ {
		key, value, inline := strings.Cut(strings.TrimPrefix(args[i], "--"), "=")
		known := strings.HasPrefix(args[i], "--")
		if known {
			known = false
			for _, n := range names {
				known = known || n == key
			}
		}
		if !known {
			rest = append(rest, args[i])
			continue
		}
		if !inline && i+1 < len(args) {
			i++
			value = args[i]
		}
		out[key] = value
	}
	return out, rest
}

// password reads one line from stdin (the panel writes it there).
func password() string {
	line, _ := bufio.NewReader(os.Stdin).ReadString('\n')
	return strings.TrimRight(line, "\r\n")
}

func cliImport(args []string) error {
	f, rest := flags(args, "name", "user")
	if len(rest) != 1 {
		return errors.New("usage: vpn import FILE [--name NAME] [--user USER]")
	}
	text, err := os.ReadFile(rest[0])
	if err != nil {
		return err
	}
	name := f["name"]
	if name == "" {
		name = strings.TrimSuffix(filepath.Base(rest[0]), filepath.Ext(rest[0]))
	}
	req := &ImportRequest{Name: name, Text: string(text), Username: f["user"]}
	if req.Username != "" {
		req.Password = password()
	}
	if _, err = call(Request{Cmd: "import", Import: req}); err == nil {
		fmt.Printf("added %s\n", name)
	}
	return err
}

func cliAdd(args []string) error {
	f, rest := flags(args, "protocol", "user", "servercert")
	if len(rest) != 2 {
		return errors.New("usage: vpn add NAME SERVER [--protocol P] [--user USER] [--servercert PIN]")
	}
	req := &ImportRequest{Kind: "openconnect", Name: rest[0], Server: rest[1], Protocol: f["protocol"],
		Username: f["user"], ServerCert: f["servercert"]}
	if req.Username != "" {
		req.Password = password()
	}
	_, err := call(Request{Cmd: "import", Import: req})
	if err == nil {
		fmt.Printf("added %s\n", req.Name)
	}
	return err
}

// cliRun starts the command in vpn.slice, whose sockets the rules send
// through the VPN. vpn-anchor.service keeps the slice alive: the rules
// point at it, and a slice made anew would not match them.
func cliRun(args []string) error {
	force := len(args) > 0 && args[0] == "--force"
	if force {
		args = args[1:]
	}
	// The launcher's prefix: vpn run -- app
	if len(args) > 0 && args[0] == "--" {
		args = args[1:]
	}
	if len(args) == 0 {
		return errors.New("usage: vpn run [--force] COMMAND...")
	}
	if _, err := exec.LookPath(args[0]); err != nil {
		return fmt.Errorf("command not found: %s", args[0])
	}
	if !force {
		s, err := call(Request{Cmd: "status"})
		if err != nil {
			return err
		}
		if s.State == "off" || s.State == "failed" {
			return errors.New("the VPN is off, so this would use the normal connection; `vpn up` first, or --force")
		}
	}
	exec.Command("systemctl", "--user", "start", "vpn-anchor.service").Run()
	cmd := append([]string{"systemd-run", "--user", "--scope", "--quiet", "--collect", "--slice=vpn.slice", "--"}, args...)
	path, err := exec.LookPath(cmd[0])
	if err != nil {
		return err
	}
	return execv(path, cmd)
}

// cliAttach moves running processes into the slice: a new transient scope
// adopts them, like `systemd-run --scope` does with its own.
func cliAttach(targets []string) error {
	if len(targets) == 0 {
		return errors.New("usage: vpn attach PID|NAME...")
	}
	var pids []string
	for _, t := range targets {
		if _, err := strconv.Atoi(t); err == nil {
			pids = append(pids, t)
			continue
		}
		out, _ := exec.Command("pgrep", "-u", strconv.Itoa(os.Getuid()), "-x", "--", t).Output()
		pids = append(pids, strings.Fields(string(out))...)
	}
	if len(pids) == 0 {
		return fmt.Errorf("no such process: %s", strings.Join(targets, " "))
	}
	exec.Command("systemctl", "--user", "start", "vpn-anchor.service").Run()
	unit := fmt.Sprintf("vpn-attach-%d-%d.scope", os.Getpid(), time.Now().UnixNano()%100000)
	args := []string{"--user", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
		"org.freedesktop.systemd1.Manager", "StartTransientUnit", "ssa(sv)a(sa(sv))",
		unit, "fail", "2", "PIDs", "au", strconv.Itoa(len(pids))}
	args = append(append(args, pids...), "Slice", "s", "vpn.slice", "0")
	if out, err := exec.Command("busctl", args...).CombinedOutput(); err != nil {
		return fmt.Errorf("systemd did not move them: %s", strings.TrimSpace(string(out)))
	}
	fmt.Printf("moved %d process(es); only connections they open from now on use the VPN\n", len(pids))
	return nil
}

// runHook is what openvpn (--up) and openconnect (--script) run: it hands
// their environment (addresses, DNS...) to the daemon and waits until the
// link is set up, so they only carry traffic once it is routed.
func runHook(args []string) error {
	if len(args) == 0 {
		return errors.New("usage: vpn hook openvpn|openconnect")
	}
	env := map[string]string{}
	for _, kv := range os.Environ() {
		if k, v, ok := strings.Cut(kv, "="); ok {
			env[k] = v
		}
	}
	_, err := call(Request{Cmd: "hook", Kind: args[0], Env: env})
	return err
}
