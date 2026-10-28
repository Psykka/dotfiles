#!/usr/bin/env python3
"""Runs next to ocserv: a site on :7000 that answers with the address it
saw, and a DNS server on :53 that answers 10.10.0.53 to everything (so the
test can tell this DNS from podman's)."""
import select
import socket

site = socket.socket()
site.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
site.bind(("0.0.0.0", 7000))
site.listen()
dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
dns.bind(("0.0.0.0", 53))
while True:
    for s in select.select([site, dns], [], [])[0]:
        if s is site:
            conn, (addr, _) = site.accept()
            conn.sendall(addr.encode())
            conn.close()
        else:
            query, peer = dns.recvfrom(512)
            head = query[:2] + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
            record = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + socket.inet_aton("10.10.0.53")
            dns.sendto(head + query[12:] + record, peer)
