// vpn: WireGuard, OpenVPN and OpenConnect, with the whole system or just
// chosen apps going through the tunnel (split tunneling).
//
// The root daemon (vpnd.service) does the work; this same binary is the
// client for the terminal. The bar and the panel talk to the daemon from
// waybar/.config/waybar/vpn.py.
package main

import (
	"fmt"
	"os"
)

const usage = `Usage: vpn [status] [--json]           what is connected, and the VPNs
       vpn list                         the VPNs that were imported
       vpn up [NAME] | down             connect (the last one by default) / disconnect
       vpn toggle [NAME]                connect, or disconnect when it is on
       vpn mode [full|apps]             everything through the VPN, or just apps run with "vpn run"
       vpn import FILE [--name NAME] [--user USER]
                                        add a WireGuard .conf or an OpenVPN .ovpn
                                        (with --user, the password is read from stdin)
       vpn add NAME SERVER [--protocol P] [--user USER] [--servercert PIN]
                                        add an OpenConnect VPN (P: anyconnect, gp,
                                        fortinet, pulse, nc, f5, array)
       vpn remove NAME                  forget a VPN
       vpn run [--force] COMMAND...     start an app that goes through the VPN (apps mode)
       vpn attach PID|NAME...           move running apps in (new connections only)
       vpn daemon                       the daemon itself (root)`

func main() {
	args := os.Args[1:]
	cmd := "status"
	if len(args) > 0 {
		cmd, args = args[0], args[1:]
	}
	var err error
	switch cmd {
	case "daemon":
		runDaemon()
	case "hook":
		err = runHook(args)
	case "status":
		err = cliStatus(len(args) > 0 && args[0] == "--json")
	case "list":
		err = cliList()
	case "up":
		err = cliUp(first(args))
	case "down":
		_, err = call(Request{Cmd: "down"})
	case "toggle":
		err = cliToggle(first(args))
	case "mode":
		err = cliMode(first(args))
	case "import":
		err = cliImport(args)
	case "add":
		err = cliAdd(args)
	case "remove":
		if len(args) != 1 {
			err = fmt.Errorf("usage: vpn remove NAME")
		} else {
			_, err = call(Request{Cmd: "remove", Profile: args[0]})
		}
	case "run":
		err = cliRun(args)
	case "attach":
		err = cliAttach(args)
	default:
		fmt.Fprintln(os.Stderr, usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "vpn:", err)
		os.Exit(1)
	}
}

func first(args []string) string {
	if len(args) > 0 {
		return args[0]
	}
	return ""
}
