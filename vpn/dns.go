package main

// DNS forwarder. The tunneled traffic's port 53 is redirected here
// (routing.go), and lookups go on to the VPN's DNS servers with the mark
// that routes them through vpn0. Without a tunnel (off, or dropped with the
// kill switch) queries get no answer, so they never leak to the normal
// connection's DNS.

import (
	"context"
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"sync"
	"syscall"
	"time"
)

type forwarder struct {
	mu      sync.Mutex
	servers []string
}

func (f *forwarder) set(servers []string) {
	f.mu.Lock()
	f.servers = servers
	f.mu.Unlock()
}

func (f *forwarder) upstream() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.servers
}

var markedDialer = net.Dialer{
	Timeout: 3 * time.Second,
	Control: func(_, _ string, c syscall.RawConn) error {
		var err error
		c.Control(func(fd uintptr) {
			err = syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_MARK, markDNS)
		})
		return err
	},
}

// ask sends one query to each server in turn until one answers.
func (f *forwarder) ask(network string, query []byte) []byte {
	for _, s := range f.upstream() {
		conn, err := markedDialer.DialContext(context.Background(), network, net.JoinHostPort(s, "53"))
		if err != nil {
			continue
		}
		conn.SetDeadline(time.Now().Add(3 * time.Second))
		var answer []byte
		if network == "udp" {
			if _, err = conn.Write(query); err == nil {
				buf := make([]byte, 65535)
				var n int
				n, err = conn.Read(buf)
				answer = buf[:n]
			}
		} else {
			answer, err = tcpExchange(conn, query)
		}
		conn.Close()
		if err == nil {
			return answer
		}
	}
	return nil
}

func tcpExchange(conn net.Conn, query []byte) ([]byte, error) {
	msg := binary.BigEndian.AppendUint16(nil, uint16(len(query)))
	if _, err := conn.Write(append(msg, query...)); err != nil {
		return nil, err
	}
	return readTCP(conn)
}

func readTCP(conn net.Conn) ([]byte, error) {
	var size [2]byte
	if _, err := io.ReadFull(conn, size[:]); err != nil {
		return nil, err
	}
	msg := make([]byte, binary.BigEndian.Uint16(size[:]))
	_, err := io.ReadFull(conn, msg)
	return msg, err
}

// serve listens on loopback, IPv4 and IPv6, UDP and TCP.
func (f *forwarder) serve() error {
	for _, host := range []string{"127.0.0.1", "::1"} {
		addr := net.JoinHostPort(host, fmt.Sprint(dnsPort))
		pc, err := net.ListenPacket("udp", addr)
		if err != nil {
			return err
		}
		go f.serveUDP(pc)
		ln, err := net.Listen("tcp", addr)
		if err != nil {
			return err
		}
		go f.serveTCP(ln)
	}
	return nil
}

func (f *forwarder) serveUDP(pc net.PacketConn) {
	for {
		buf := make([]byte, 65535)
		n, from, err := pc.ReadFrom(buf)
		if err != nil {
			return
		}
		go func() {
			if answer := f.ask("udp", buf[:n]); answer != nil {
				pc.WriteTo(answer, from)
			}
		}()
	}
}

func (f *forwarder) serveTCP(ln net.Listener) {
	for {
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		go func() {
			defer conn.Close()
			for {
				conn.SetDeadline(time.Now().Add(10 * time.Second))
				query, err := readTCP(conn)
				if err != nil {
					return
				}
				answer := f.ask("tcp", query)
				if answer == nil {
					return
				}
				msg := binary.BigEndian.AppendUint16(nil, uint16(len(answer)))
				if _, err := conn.Write(append(msg, answer...)); err != nil {
					return
				}
			}
		}()
	}
}
