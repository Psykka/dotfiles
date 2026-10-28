package main

// Split routing, the same for every kind of VPN: they all end in the link
// vpn0, and a routing table with the networks the VPN carries decides what
// goes through it.
//
//	full: everything but the tunnel's own packets      -> table 5650 -> vpn0
//	apps: sockets of the user's vpn.slice (fwmark)     -> table 5650 -> vpn0
//
// What the table doesn't hold goes on to the normal routes. A VPN that is
// a way out to the internet (its networks include 0.0.0.0/0) holds the
// default route, and under it an unreachable one: when the link goes away
// (the connection dropped) that traffic is cut instead of leaking out of
// the normal connection. That is the kill switch; it lasts until `vpn down`
// removes the rules. A VPN into an office network just holds that network.
//
// When the VPN has DNS servers, port 53 traffic that should be tunneled is
// redirected to the daemon's own DNS forwarder (dns.go), which asks them
// through vpn0.

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strings"
)

const (
	linkName = "vpn0"
	table    = "5650"
	nftTable = "vpn"
	dnsPort  = 5653

	// Sockets of the user's vpn.slice, in apps mode
	markApps = 0x5650
	// The tunnel's own packets: WireGuard's (its fwmark) and those of the
	// daemon and its children (openvpn, openconnect), which must leave
	// through the normal connection or they would loop into the tunnel
	markBypass = 0x5651
	// The DNS forwarder's lookups: always through the tunnel
	markDNS = 0x5652
)

func run(name string, args ...string) error {
	out, err := exec.Command(name, args...).CombinedOutput()
	if err != nil {
		msg := strings.TrimSpace(string(out))
		if msg == "" {
			msg = err.Error()
		}
		return fmt.Errorf("%s %s: %s", name, strings.Join(args, " "), msg)
	}
	return nil
}

func runInput(input, name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.Stdin = strings.NewReader(input)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("%s: %s", name, strings.TrimSpace(string(out)))
	}
	return nil
}

func ip(args ...string) error { return run("ip", args...) }

// The cgroup of this process (systemd: system.slice/vpnd.service), whose
// sockets bypass the tunnel. Its children (openvpn, openconnect) stay in it.
func ownCgroup() string {
	data, err := os.ReadFile("/proc/self/cgroup")
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(data), "\n") {
		if path, ok := strings.CutPrefix(line, "0::/"); ok {
			return path
		}
	}
	return ""
}

// The slice apps run in to use the tunnel (`vpn run`), in the user's
// systemd --user manager.
func slicePath(uid int) string {
	return fmt.Sprintf("user.slice/user-%d.slice/user@%d.service/vpn.slice", uid, uid)
}

func level(cgroup string) int { return strings.Count(cgroup, "/") + 1 }

// ensureSlice starts vpn-anchor.service in the user's systemd when
// vpn.slice isn't there (just installed, say): the rules need it to exist.
func ensureSlice(uid int) error {
	if _, err := os.Stat(filepath.Join("/sys/fs/cgroup", slicePath(uid))); err == nil {
		return nil
	}
	u, err := user.LookupId(fmt.Sprint(uid))
	if err != nil {
		return err
	}
	if err := run("systemctl", "--user", "--machine="+u.Username+"@.host", "start", "vpn-anchor.service"); err != nil {
		return fmt.Errorf("apps mode needs vpn.slice: %v", err)
	}
	return nil
}

func ruleset(mode string, uid int, dns bool) string {
	var out strings.Builder
	marks := fmt.Sprintf("{ %#x, %#x }", markBypass, markDNS)
	slice := slicePath(uid)
	match := fmt.Sprintf("socket cgroupv2 level %d %q", level(slice), slice)

	fmt.Fprintf(&out, "table inet %s {\n", nftTable)
	out.WriteString("    chain output {\n        type route hook output priority mangle; policy accept;\n")
	fmt.Fprintf(&out, "        meta mark %s return\n", marks)
	if self := ownCgroup(); self != "" {
		fmt.Fprintf(&out, "        socket cgroupv2 level %d %q meta mark set %#x return\n", level(self), self, markBypass)
	}
	if mode == "apps" {
		fmt.Fprintf(&out, "        %s meta mark set %#x ct mark set meta mark\n", match, markApps)
	}
	out.WriteString("    }\n")

	// Replies of the apps' connections carry their mark back, so the
	// reverse-path check finds them on vpn0 (src_valid_mark)
	out.WriteString("    chain prerouting {\n        type filter hook prerouting priority mangle; policy accept;\n")
	fmt.Fprintf(&out, "        ct mark %#x meta mark set ct mark\n    }\n", markApps)

	// A socket picks its source address before the mark reroutes it: an
	// app's would carry the normal connection's address into the tunnel,
	// and in full mode the daemon's the tunnel's address out of it
	out.WriteString("    chain postrouting {\n        type nat hook postrouting priority srcnat; policy accept;\n")
	fmt.Fprintf(&out, "        oifname %q masquerade\n", linkName)
	fmt.Fprintf(&out, "        meta mark %#x masquerade\n    }\n", markBypass)

	if dns {
		out.WriteString("    chain dns {\n        type nat hook output priority dstnat; policy accept;\n")
		fmt.Fprintf(&out, "        meta mark %s return\n", marks)
		who := ""
		if mode == "apps" {
			who = match + " "
		}
		fmt.Fprintf(&out, "        %smeta l4proto { tcp, udp } th dport 53 redirect to :%d\n    }\n", who, dnsPort)
	}
	out.WriteString("}\n")
	return out.String()
}

// gateway: the VPN is a way out to the internet, not just into some networks.
func gateway(routes []string) bool {
	half := 0
	for _, r := range routes {
		switch r {
		case "0.0.0.0/0", "::/0":
			return true
		case "0.0.0.0/1", "128.0.0.0/1":
			half++
		}
	}
	return half == 2
}

// installRouting points the chosen traffic at vpn0, which must be up.
func installRouting(mode string, uid int, link *linkInfo, dns bool) error {
	removeRouting()
	if mode == "apps" {
		if err := ensureSlice(uid); err != nil {
			return err
		}
	}
	// Lets the reverse-path check use the marks
	os.WriteFile("/proc/sys/net/ipv4/conf/all/src_valid_mark", []byte("1"), 0o644)

	var steps [][]string
	for _, r := range link.routes {
		fam := "-4"
		if strings.Contains(r, ":") {
			fam = "-6"
		}
		if r == "0.0.0.0/0" || r == "::/0" {
			r = "default"
		}
		steps = append(steps, []string{fam, "route", "replace", r, "dev", linkName, "table", table})
	}
	if gateway(link.routes) {
		// Also for IPv6 when the VPN has none: it would leak around it
		steps = append(steps,
			[]string{"-4", "route", "replace", "unreachable", "default", "metric", "4096", "table", table},
			[]string{"-6", "route", "replace", "unreachable", "default", "metric", "4096", "table", table})
	}
	// The server: its packets carry the tunnel, they can't go into it.
	// openvpn and openconnect are kept out by the daemon's cgroup too, but
	// that one is just the root when the daemon runs outside systemd
	if addr := net.ParseIP(link.server); addr != nil {
		fam, bits := "-4", "/32"
		if addr.To4() == nil {
			fam, bits = "-6", "/128"
		}
		steps = append(steps, []string{fam, "rule", "add", "to", link.server + bits, "table", "main", "priority", "5646"})
	}
	for _, fam := range []string{"-4", "-6"} {
		steps = append(steps, []string{fam, "rule", "add", "fwmark", hex(markDNS), "table", table, "priority", "5647"})
		if mode == "apps" {
			// LAN and link routes still work for the apps, the default route doesn't
			steps = append(steps,
				[]string{fam, "rule", "add", "fwmark", hex(markApps), "table", "main", "suppress_prefixlength", "0", "priority", "5648"},
				[]string{fam, "rule", "add", "fwmark", hex(markApps), "table", table, "priority", "5650"})
		} else {
			steps = append(steps,
				[]string{fam, "rule", "add", "table", "main", "suppress_prefixlength", "0", "priority", "5648"},
				[]string{fam, "rule", "add", "not", "fwmark", hex(markBypass), "table", table, "priority", "5650"})
		}
	}
	for _, s := range steps {
		if err := ip(s...); err != nil {
			removeRouting()
			return err
		}
	}
	if err := runInput(ruleset(mode, uid, dns), "nft", "-f", "-"); err != nil {
		removeRouting()
		return err
	}
	return nil
}

func removeRouting() {
	for _, fam := range []string{"-4", "-6"} {
		for _, prio := range []string{"5646", "5647", "5648", "5650"} {
			for ip(fam, "rule", "del", "priority", prio) == nil {
			}
		}
		ip(fam, "route", "flush", "table", table)
	}
	run("nft", "delete", "table", "inet", nftTable)
}

func hex(n int) string { return fmt.Sprintf("%#x", n) }

func deleteLink() { ip("link", "del", linkName) }

// configureLink gives vpn0 its addresses and MTU and brings it up, for the
// VPNs that leave that to their script (openconnect) or to us (WireGuard).
func configureLink(addrs []string, mtu int) error {
	for _, a := range addrs {
		fam := "-4"
		if strings.Contains(a, ":") {
			fam = "-6"
		}
		if err := ip(fam, "address", "add", a, "dev", linkName); err != nil {
			return err
		}
	}
	if mtu <= 0 {
		mtu = 1420
	}
	return ip("link", "set", "mtu", fmt.Sprint(mtu), "up", "dev", linkName)
}

// linkStats: bytes in and out of vpn0 (from ip, which unlike /sys follows
// the network namespace)
func linkStats() (rx, tx uint64) {
	out, err := exec.Command("ip", "-j", "-s", "link", "show", linkName).Output()
	if err != nil {
		return 0, 0
	}
	var links []struct {
		Stats struct {
			Rx struct{ Bytes uint64 } `json:"rx"`
			Tx struct{ Bytes uint64 } `json:"tx"`
		} `json:"stats64"`
	}
	if json.Unmarshal(out, &links) != nil || len(links) == 0 {
		return 0, 0
	}
	return links[0].Stats.Rx.Bytes, links[0].Stats.Tx.Bytes
}
