#!/usr/bin/env python3
"""End-to-end test of vpn/ (the VPN daemon) that never touches this
machine's network or needs root: it runs in a user + network namespace of
its own, with a pretend internet next to it.

    client namespace (the daemon)  --veth-->  server namespace
      10.0.0.2                                10.0.0.1     the normal gateway, "ISP" DNS
                                              203.0.113.5  a site: says which address it saw
                                              10.9.0.1     WireGuard end, the VPN's DNS

Checks the full mode, the apps mode (a process in vpn.slice goes through
the tunnel, the rest doesn't), DNS through the tunnel, the kill switch, a
VPN that fails to connect, and an OpenConnect stand-in driving the hook.

The apps mode needs a cgroup inside vpn.slice of this user's systemd, so it
starts a throwaway unit there (vpn-anchor-test.service), stopped at the end.

Usage: dev/vpn-test.py
"""
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
# Inside the namespace this process is root; the cgroups are the real user's
UID = int(os.environ.setdefault("VPN_TEST_UID", str(os.getuid())))
USER_CG = f"/sys/fs/cgroup/user.slice/user-{UID}.slice/user@{UID}.service"
SLICE = f"{USER_CG}/vpn.slice"
SITE = ("203.0.113.5", 7000)

failures = []


def sh(*args, check=True, **kw):
    return subprocess.run(args, check=check, capture_output=True, text=True, **kw)


def outer():
    work = tempfile.mkdtemp(prefix="vpn-test-")
    try:
        for name, pkg in (("vpn", "."), ("wgserver", "./test/wgserver")):
            sh("go", "build", "-o", f"{work}/{name}", pkg, cwd=f"{REPO}/vpn")
        # vpn.slice has to exist for the apps mode rules
        sh("systemd-run", "--user", "--quiet", "--unit=vpn-anchor-test", "--slice=vpn.slice", "sleep", "600")
        # Its own scope, so this test may move a process into vpn.slice
        # (both under user@.service, which this user owns)
        r = subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "unshare", "-rnm",
                            "--propagation", "private", sys.executable, __file__, "--inside", work])
        sys.exit(r.returncode)
    finally:
        subprocess.run(["systemctl", "--user", "stop", "vpn-anchor-test.service"], capture_output=True)
        shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------- pretend internet

def serve():
    """The server namespace's services: the site and two DNS servers whose
    answer says which one replied."""
    site = socket.socket()
    site.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    site.bind(("0.0.0.0", SITE[1]))
    site.listen()
    dns = []
    for host in ("10.0.0.1", "10.9.0.1"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((host, 53))
        dns.append(s)
    import select
    while True:
        ready, _, _ = select.select([site] + dns, [], [])
        for s in ready:
            if s is site:
                conn, (addr, _) = site.accept()
                conn.sendall(addr.encode())
                conn.close()
            else:
                query, peer = s.recvfrom(512)
                answer_ip = "10.0.0.53" if s.getsockname()[0] == "10.0.0.1" else "10.9.0.53"
                # Header: same id, response, one question, one answer
                head = query[:2] + b"\x81\x80" + b"\x00\x01\x00\x01\x00\x00\x00\x00"
                question = query[12:]
                record = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + socket.inet_aton(answer_ip)
                s.sendto(head + question + record, peer)


def whoami(host=SITE[0]):
    """The address the site saw, or None when it can't be reached."""
    try:
        with socket.create_connection((host, SITE[1]), timeout=2) as s:
            return s.recv(64).decode()
    except OSError:
        return None


def lookup(server="10.0.0.1"):
    """Asks server for example.com; the answer tells who really replied."""
    query = struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + b"\x07example\x03com\x00\x00\x01\x00\x01"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    try:
        s.sendto(query, (server, 53))
        answer = s.recv(512)
        return socket.inet_ntoa(answer[-4:])
    except OSError:
        return None
    finally:
        s.close()


def probe():
    """Run as a child: prints what whoami and lookup give, as JSON."""
    print(json.dumps({"ip": whoami(), "dns": lookup()}))


# -------------------------------------------------------------- the test

class Env:
    def __init__(self, work):
        self.work = work
        self.vpn = f"{work}/vpn"
        self.env = dict(os.environ, VPN_SOCKET=f"{work}/vpnd.sock", VPN_STATE_DIR=f"{work}/state",
                        VPN_USERS=f"{work}/users")
        with open(f"{work}/users", "w") as f:
            f.write(f"{UID}\n")
        self.server = subprocess.Popen(["unshare", "-n", "sleep", "infinity"])
        time.sleep(0.2)
        self.daemon = None

    def srv(self, *args):
        return sh("nsenter", "-t", str(self.server.pid), "-n", *args)

    def cli(self, *args, input=None, check=True):
        return sh(self.vpn, *args, env=self.env, input=input, check=check)

    def status(self):
        return json.loads(self.cli("status", "--json").stdout)

    def setup(self):
        sh("ip", "link", "set", "lo", "up")
        sh("ip", "link", "add", "veth0", "type", "veth", "peer", "name", "veth1", "netns", str(self.server.pid))
        sh("ip", "address", "add", "10.0.0.2/24", "dev", "veth0")
        sh("ip", "link", "set", "veth0", "up")
        sh("ip", "route", "add", "default", "via", "10.0.0.1")

        server_key, server_pub = sh(f"{self.work}/wgserver", "genkey").stdout.split()
        client_key, client_pub = sh(f"{self.work}/wgserver", "genkey").stdout.split()
        self.srv("ip", "link", "set", "lo", "up")
        self.srv("ip", "address", "add", "203.0.113.5/32", "dev", "lo")
        self.srv("ip", "address", "add", "10.0.0.1/24", "dev", "veth1")
        self.srv("ip", "link", "set", "veth1", "up")
        self.srv("ip", "link", "add", "wgs", "type", "wireguard")
        self.srv(f"{self.work}/wgserver", "wgs", server_key, "51820", client_pub, "10.9.0.2/32")
        self.srv("ip", "address", "add", "10.9.0.1/24", "dev", "wgs")
        self.srv("ip", "link", "set", "wgs", "up")
        self.services = subprocess.Popen(["nsenter", "-t", str(self.server.pid), "-n",
                                          sys.executable, __file__, "--serve"])

        with open(f"{self.work}/home.conf", "w") as f:
            f.write(f"""[Interface]
PrivateKey = {client_key}
Address = 10.9.0.2/32
DNS = 10.9.0.1, vpn.internal
PostUp = touch {self.work}/pwned

[Peer]
PublicKey = {server_pub}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 10.0.0.1:51820
""")
        self.start_daemon("daemon.log")

    def start_daemon(self, log):
        """The daemon, in a cgroup of its own like vpnd.service: what runs
        there bypasses the tunnel, so the test's probes must not."""
        cg = f"{USER_CG}/vpn-test-daemon"
        os.makedirs(cg, exist_ok=True)

        def join():
            with open(f"{cg}/cgroup.procs", "w") as f:
                f.write(str(os.getpid()))
        if os.path.exists(f"{self.work}/vpnd.sock"):
            os.remove(f"{self.work}/vpnd.sock")
        self.daemon = subprocess.Popen([self.vpn, "daemon"], env=self.env, preexec_fn=join,
                                       stderr=open(f"{self.work}/{log}", "w"))
        for _ in range(50):
            if os.path.exists(f"{self.work}/vpnd.sock"):
                break
            time.sleep(0.1)
        time.sleep(0.5)

    def openvpn_server(self):
        """An OpenVPN server on 10.0.0.1:1194 that pushes 10.9.0.1 as DNS and
        takes the login me / secret, and client.ovpn with inline certs."""
        w = f"{self.work}/ovpn"
        os.makedirs(w)

        def cert(name, *ext):
            sh("openssl", "req", "-x509" if name == "ca" else "-new", "-newkey", "ec", "-pkeyopt",
               "ec_paramgen_curve:prime256v1", "-nodes", "-subj", f"/CN={name}", "-keyout", f"{w}/{name}.key",
               "-out", f"{w}/{name}.{'crt' if name == 'ca' else 'csr'}", "-days", "2")
            if name != "ca":
                with open(f"{w}/{name}.ext", "w") as f:
                    f.write("\n".join(ext) + "\n")
                sh("openssl", "x509", "-req", "-in", f"{w}/{name}.csr", "-CA", f"{w}/ca.crt", "-CAkey",
                   f"{w}/ca.key", "-CAcreateserial", "-out", f"{w}/{name}.crt", "-days", "2",
                   "-extfile", f"{w}/{name}.ext")
        cert("ca")
        cert("server", "extendedKeyUsage=serverAuth", "keyUsage=digitalSignature,keyAgreement")
        cert("client", "extendedKeyUsage=clientAuth", "keyUsage=digitalSignature,keyAgreement")
        with open(f"{w}/check", "w") as f:
            f.write('#!/bin/sh\n{ read -r user; read -r password; } < "$1"\n'
                    'echo "[$user][$password] $1 $(id -u)" >> "$0.log"; [ "$user" = me ] && [ "$password" = secret ]\n')
        os.chmod(f"{w}/check", 0o755)
        self.openvpn = subprocess.Popen(
            ["nsenter", "-t", str(self.server.pid), "-n", "openvpn", "--dev", "tunsrv", "--dev-type", "tun",
             "--local", "10.0.0.1", "--port", "1194", "--proto", "udp", "--server", "10.8.0.0", "255.255.255.0",
             "--topology", "subnet", "--ca", f"{w}/ca.crt", "--cert", f"{w}/server.crt", "--key", f"{w}/server.key",
             "--dh", "none", "--disable-dco", "--push", "dhcp-option DNS 10.9.0.1", "--push", "redirect-gateway def1",
             "--script-security", "2", "--auth-user-pass-verify", f"{w}/check", "via-file", "--verb", "1"],
            stdout=open(f"{w}/server.log", "w"), stderr=subprocess.STDOUT)
        inline = lambda tag, path: f"<{tag}>\n{open(path).read()}</{tag}>\n"
        with open(f"{self.work}/client.ovpn", "w") as f:
            f.write("client\ndev tun\nproto udp\nremote 10.0.0.1 1194\nremote-cert-tls server\n"
                    "auth-user-pass\nverb 3\n" + inline("ca", f"{w}/ca.crt") +
                    inline("cert", f"{w}/client.crt") + inline("key", f"{w}/client.key"))
        time.sleep(1)

    def in_slice(self):
        """What a process inside vpn.slice sees (an app `vpn run` started)."""
        cg = f"{SLICE}/vpn-test-app"
        os.makedirs(cg, exist_ok=True)

        def join():
            with open(f"{cg}/cgroup.procs", "w") as f:
                f.write(str(os.getpid()))
        out = subprocess.run([sys.executable, __file__, "--probe"], preexec_fn=join,
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def cleanup(self):
        for p in (self.daemon, getattr(self, "services", None), getattr(self, "openvpn", None), self.server):
            if p:
                p.terminate()
        if self.daemon:
            self.daemon.wait()
        for cg in (f"{SLICE}/vpn-test-app", f"{USER_CG}/vpn-test-daemon"):
            try:
                os.rmdir(cg)
            except OSError:
                pass


def expect(what, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {what}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        failures.append(what)


def wait_state(t, state, timeout=10):
    for _ in range(timeout * 10):
        s = t.status()
        if s["state"] == state:
            return s
        time.sleep(0.1)
    return t.status()


def inside(work):
    t = Env(work)
    try:
        t.setup()
        print("without VPN")
        expect("site sees", whoami(), "10.0.0.2")
        expect("dns from", lookup(), "10.0.0.53")

        print("import")
        r = t.cli("import", f"{work}/home.conf", "--name", "Home", check=False)
        expect("import", r.returncode, 0)
        bad = t.cli("import", f"{work}/home.conf", "--name", "Home", check=False)
        expect("same name refused", bad.returncode != 0, True)
        with open(f"{work}/evil.ovpn", "w") as f:
            f.write("client\nremote example.org 1194\nup /bin/sh\n")
        bad = t.cli("import", f"{work}/evil.ovpn", check=False)
        expect("ovpn with `up` refused", "not allowed" in bad.stderr, True)
        with open(f"{work}/files.ovpn", "w") as f:
            f.write("client\nremote example.org 1194\nca ca.crt\n")
        bad = t.cli("import", f"{work}/files.ovpn", check=False)
        expect("ovpn with outside files refused", "separate file" in bad.stderr, True)

        print("full mode")
        r = t.cli("up", "Home", check=False)
        expect("up", (r.returncode, r.stdout.strip(), r.stderr.strip()), (0, "Home: on", ""))
        expect("PostUp not run", os.path.exists(f"{work}/pwned"), False)
        expect("site sees", whoami(), "10.9.0.2")
        expect("dns from", lookup(), "10.9.0.53")
        s = t.status()
        expect("status dns", s["dns"], ["10.9.0.1"])
        expect("handshake", s["handshake"] > 0, True)

        print("apps mode")
        r = t.cli("mode", "apps", check=False)
        expect("mode apps", (r.returncode, r.stderr.strip()), (0, ""))
        expect("site sees", whoami(), "10.0.0.2")
        expect("dns from", lookup(), "10.0.0.53")
        expect("app in vpn.slice", t.in_slice(), {"ip": "10.9.0.2", "dns": "10.9.0.53"})

        print("kill switch (link gone)")
        sh("ip", "link", "del", "vpn0")
        expect("app in vpn.slice", t.in_slice(), {"ip": None, "dns": None})
        expect("site sees", whoami(), "10.0.0.2")
        t.cli("down")
        expect("after down, app", t.in_slice(), {"ip": "10.0.0.2", "dns": "10.0.0.53"})

        print("a VPN into one network, without DNS (the rest stays normal)")
        with open(f"{work}/net.conf", "w") as f:
            f.write(open(f"{work}/home.conf").read().replace("0.0.0.0/0, ::/0", "10.9.0.0/24")
                    .replace("DNS = 10.9.0.1, vpn.internal\n", ""))
        t.cli("import", f"{work}/net.conf", "--name", "Net")
        t.cli("mode", "full")
        r = t.cli("up", "Net", check=False)
        expect("up", (r.returncode, r.stderr.strip()), (0, ""))
        expect("site sees", whoami(), "10.0.0.2")
        expect("dns from", lookup(), "10.0.0.53")
        expect("its network", whoami("10.9.0.1"), "10.9.0.2")
        s = t.status()
        expect("status", (s["routes"], s["dns"]), (["10.9.0.0/24"], []))
        t.cli("mode", "apps")
        expect("app in vpn.slice", t.in_slice(), {"ip": "10.0.0.2", "dns": "10.0.0.53"})
        expect("outside, its network", whoami("10.9.0.1"), "10.0.0.2")
        t.cli("down")

        print("a VPN that fails")
        with open(f"{work}/broken.conf", "w") as f:
            f.write(open(f"{work}/home.conf").read().replace("10.0.0.1:51820", "no-such-host.invalid:51820"))
        t.cli("import", f"{work}/broken.conf")
        r = t.cli("up", "broken", check=False)
        expect("up fails", r.returncode, 1)
        s = t.status()
        expect("state", s["state"], "failed")
        expect("rules gone", sh("ip", "rule", "show", "priority", "5650").stdout, "")

        print("openconnect stand-in (drives the hook)")
        fake = f"{work}/bin"
        os.makedirs(fake, exist_ok=True)
        with open(f"{fake}/openconnect", "w") as f:
            f.write("""#!/bin/sh
for a; do case $a in --script=*) script=${a#--script=} ;; esac; done
read -r password
[ "$password" = secret ] || { echo "Login failed" >&2; exit 1; }
ip tuntap add vpn0 mode tun || exit 1
reason=connect TUNDEV=vpn0 INTERNAL_IP4_ADDRESS=10.9.0.2 INTERNAL_IP4_DNS=10.9.0.1 INTERNAL_IP4_MTU=1300 \\
    sh -c "$script" || { echo "script failed" >&2; exit 1; }
exec sleep infinity
""")
        os.chmod(f"{fake}/openconnect", 0o755)
        # The real openvpn, without the kernel offload (DCO), which a user
        # namespace may not use
        with open(f"{fake}/openvpn", "w") as f:
            f.write(f'#!/bin/sh\nexec {shutil.which("openvpn")} "$@" --disable-dco\n')
        os.chmod(f"{fake}/openvpn", 0o755)
        # The daemon runs the VPN programs: restart it with the stand-in first in PATH
        t.daemon.terminate()
        t.daemon.wait()
        t.env["PATH"] = f"{fake}:{os.environ['PATH']}"
        t.start_daemon("daemon2.log")
        expect("mode kept", t.status()["mode"], "apps")
        t.cli("add", "Work", "vpn.example.com", "--protocol", "gp", "--user", "me", input="wrong\n")
        r = t.cli("up", "Work", check=False)
        expect("wrong password fails", "Login failed" in r.stderr, True)
        t.cli("remove", "Work")
        t.cli("add", "Work", "vpn.example.com", "--protocol", "gp", "--user", "me", input="secret\n")
        r = t.cli("up", "Work", check=False)
        expect("up", (r.returncode, r.stderr.strip()), (0, ""))
        s = t.status()
        expect("address", s["addresses"], ["10.9.0.2/32"])
        expect("mtu", json.loads(sh("ip", "-j", "link", "show", "vpn0").stdout)[0]["mtu"], 1300)
        subprocess.run(["pkill", "-P", str(t.daemon.pid)])
        s = wait_state(t, "dropped")
        expect("dropped", s["state"], "dropped")
        expect("rules kept (kill switch)", "5650" in sh("ip", "rule", "show", "priority", "5650").stdout, True)
        t.cli("down")
        expect("rules gone after down", sh("ip", "rule", "show", "priority", "5650").stdout, "")
        expect("nft table gone", sh("nft", "list", "tables").stdout.strip(), "")

        print("openvpn (a real server, with a login)")
        t.openvpn_server()
        t.cli("mode", "full")
        t.cli("import", f"{work}/client.ovpn", "--name", "Office", "--user", "me", input="wrong\n")
        r = t.cli("up", "Office", check=False)
        expect("wrong password fails", "AUTH_FAILED" in r.stderr, True)
        t.cli("remove", "Office")
        bad = t.cli("import", f"{work}/client.ovpn", "--name", "Office", check=False)
        expect("login required", "username and password" in bad.stderr, True)
        t.cli("import", f"{work}/client.ovpn", "--name", "Office", "--user", "me", input="secret\n")
        r = t.cli("up", "Office", check=False)
        expect("up", (r.returncode, r.stdout.strip(), r.stderr.strip()), (0, "Office: on", ""))
        expect("site sees", whoami(), "10.8.0.2")
        expect("dns from", lookup(), "10.9.0.53")
        expect("status dns", t.status()["dns"], ["10.9.0.1"])
        t.cli("down")
        expect("after down", whoami(), "10.0.0.2")
    finally:
        t.cleanup()
    if failures:
        print(f"\n{len(failures)} failed; daemon log in the run's work dir is gone, rerun to see it")
        for name in ("daemon.log", "daemon2.log", "ovpn/server.log"):
            try:
                print(f"--- {name}\n" + open(f"{work}/{name}").read())
            except OSError:
                pass
        sys.exit(1)
    print("\nall good")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--inside"]:
        inside(sys.argv[2])
    elif sys.argv[1:2] == ["--serve"]:
        serve()
    elif sys.argv[1:2] == ["--probe"]:
        probe()
    else:
        outer()
