#!/bin/sh
# OpenConnect against a real server: ocserv in one podman container, and
# vpn/'s daemon with the real openconnect in another, on a network of their
# own. Nothing touches this machine's network. (dev/vpn-test.py covers the
# rest without containers; OpenConnect needs a real ocserv.)
#
#   ocserv  10.10.0.1 in the tunnel: a site on :7000 that says which address
#           it saw, and a DNS server answering 10.10.0.53 (serve.py)
#   client  connects as me / secret, checks that the site sees its tunnel
#           address and that lookups reach the VPN's DNS, then disconnects
#
# Usage: dev/vpn-servers/run.sh        (builds the image the first time)
set -eu

here=$(cd "$(dirname "$0")" && pwd)
image=localhost/vpn-test-servers
work=$(mktemp -d)
trap '[ -n "${KEEP:-}" ] && podman logs vpn-test-ocserv 2>&1 | tail -${KEEP}; podman rm -f -t 0 vpn-test-ocserv vpn-test-client >/dev/null 2>&1; podman network rm vpn-test >/dev/null 2>&1; rm -rf "$work"' EXIT

podman image exists $image || podman build -t $image "$here"
CGO_ENABLED=0 go build -C "$here/../../vpn" -o "$work/vpn" .

# Server: a certificate, the user me / secret, and a config that pushes a
# DNS server and the default route
cd "$work"
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -subj /CN=ocserv \
    -keyout server.key -out server.crt -days 2 2>/dev/null
pin="pin-sha256:$(openssl x509 -in server.crt -pubkey -noout | openssl pkey -pubin -outform der |
    openssl dgst -sha256 -binary | base64)"
cat > ocserv.conf <<CONF
auth = "plain[passwd=/etc/ocserv/passwd]"
tcp-port = 443
udp-port = 443
socket-file = /run/ocserv.socket
server-cert = /etc/ocserv/server.crt
server-key = /etc/ocserv/server.key
isolate-workers = false
device = vpns
ipv4-network = 10.10.0.0/24
dns = 10.10.0.1
route = default
CONF

podman rm -f -t 0 vpn-test-ocserv vpn-test-client >/dev/null 2>&1 || true   # left by a run that was killed
podman network exists vpn-test || podman network create vpn-test >/dev/null
podman run -d -e OCSERV_DEBUG="${OCSERV_DEBUG:-0}" --name vpn-test-ocserv --network vpn-test --cap-add NET_ADMIN --device /dev/net/tun --security-opt label=disable \
    -v "$work:/srv:Z" -v "$here/serve.py:/serve.py:ro,Z" $image \
    sh -c 'cp /srv/ocserv.conf /srv/server.* /etc/ocserv/ &&
        printf "secret\nsecret\n" | ocpasswd -c /etc/ocserv/passwd me &&
        { python3 /serve.py & exec ocserv -f -d ${OCSERV_DEBUG:-0} -c /etc/ocserv/ocserv.conf; }' >/dev/null

cat > client.sh <<CLIENT
#!/bin/sh
fail=0
check() { if [ "\$2" = "\$3" ]; then echo "  ok   \$1: \$2"; else echo "  FAIL \$1: \$2 (want \$3)"; fail=1; fi; }
site() { python3 -c 'import socket; s = socket.create_connection(("10.10.0.1", 7000), timeout=3); print(s.recv(64).decode())' 2>/dev/null || echo none; }
dns() { python3 -c '
import socket, struct
q = struct.pack(">HHHHHH", 1, 0x100, 1, 0, 0, 0) + b"\x07example\x03com\x00\x00\x01\x00\x01"
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(3)
s.sendto(q, (open("/etc/resolv.conf").read().split("nameserver ")[1].split()[0], 53))
print(socket.inet_ntoa(s.recv(512)[-4:]))' 2>/dev/null || echo none; }

echo root > /etc/vpn-users
export VPN_USERS=/etc/vpn-users
/srv/vpn daemon 2>/srv/daemon.log &
sleep 0.5
echo "wrong password"
echo wrong | /srv/vpn add Bad vpn-test-ocserv --protocol anyconnect --user me --servercert "$pin" >/dev/null
/srv/vpn up Bad >/dev/null 2>&1; check "fails" \$? 1
echo "openconnect"
echo secret | /srv/vpn add Work vpn-test-ocserv --protocol anyconnect --user me --servercert "$pin" >/dev/null
out=\$(timeout 30 /srv/vpn up Work 2>&1); check "up" "\$out" "Work: on"
check "site sees" "\$(site | cut -d. -f1-3)" "10.10.0"
check "dns from" "\$(dns)" "10.10.0.53"
/srv/vpn status
/srv/vpn down
check "after down, dns from" "\$(dns | grep -c 10.10.0.53)" "0"
[ \$fail = 0 ] && echo "all good" || { echo "--- daemon log"; tail -30 /srv/daemon.log; }
exit \$fail
CLIENT
chmod +x client.sh
sleep 2
podman run --rm --name vpn-test-client --network vpn-test --cap-add NET_ADMIN --device /dev/net/tun --security-opt label=disable \
    -v "$work:/srv:Z" $image /srv/client.sh
