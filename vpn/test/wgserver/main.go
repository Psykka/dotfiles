// wgserver: the other end of the tunnel in dev/vpn-test.sh (this machine
// has no wg tool).
//
//	wgserver genkey                       prints a private and a public key
//	wgserver IFACE PRIVATE PORT PEER IP   sets up IFACE (already created)
package main

import (
	"fmt"
	"net"
	"os"

	"golang.zx2c4.com/wireguard/wgctrl"
	"golang.zx2c4.com/wireguard/wgctrl/wgtypes"
)

func main() {
	if len(os.Args) == 2 && os.Args[1] == "genkey" {
		k, _ := wgtypes.GeneratePrivateKey()
		fmt.Println(k.String(), k.PublicKey().String())
		return
	}
	if len(os.Args) != 6 {
		fmt.Fprintln(os.Stderr, "usage: wgserver genkey | IFACE PRIVATE PORT PEER IP")
		os.Exit(2)
	}
	priv, err := wgtypes.ParseKey(os.Args[2])
	check(err)
	peer, err := wgtypes.ParseKey(os.Args[4])
	check(err)
	var port int
	fmt.Sscan(os.Args[3], &port)
	_, allowed, err := net.ParseCIDR(os.Args[5])
	check(err)
	wg, err := wgctrl.New()
	check(err)
	check(wg.ConfigureDevice(os.Args[1], wgtypes.Config{PrivateKey: &priv, ListenPort: &port,
		Peers: []wgtypes.PeerConfig{{PublicKey: peer, AllowedIPs: []net.IPNet{*allowed}}}}))
}

func check(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
