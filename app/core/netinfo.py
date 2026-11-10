"""What the Connection panel needs to know about the home network, standard library only:
this computer's address, the router's address, and a second way to open the download port (NAT-PMP)
for routers that don't answer UPnP. Everything is best-effort and never raises out.
"""
from __future__ import annotations

import re
import socket
import struct
import subprocess
import sys

NATPMP_PORT = 5351


def local_ip() -> str:
    """This computer's address on the home network ("" when offline). No packet is sent."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 80))                    # a documentation address: only picks the route
        ip = s.getsockname()[0]
        return "" if ip.startswith(("0.", "127.")) else ip
    except OSError:
        return ""
    finally:
        s.close()


def _run(args: list[str]) -> str:
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        return subprocess.run(args, capture_output=True, text=True, timeout=6, creationflags=flags).stdout
    except Exception:
        return ""


def parse_gateway(text: str, platform: str) -> str:
    """The default gateway out of the OS's own routing table printout."""
    if platform == "win32":                             # route print -4 0.0.0.0 ->  0.0.0.0  0.0.0.0  <gateway>  <iface>  <metric>
        m = re.search(r"(?m)^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)\s", text)
    elif platform == "darwin":                          # route -n get default ->  gateway: 192.168.1.1
        m = re.search(r"(?m)^\s*gateway:\s*(\d+\.\d+\.\d+\.\d+)", text)
    else:                                               # ip route show default ->  default via 192.168.1.1 dev ...
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", text)
    return m.group(1) if m else ""


def router_ip() -> str:
    """The router's address: the default gateway, or failing that the usual x.x.x.1 of this network."""
    cmd = {"win32": ["route", "print", "-4", "0.0.0.0"], "darwin": ["route", "-n", "get", "default"]}.get(
        sys.platform, ["ip", "route", "show", "default"])
    gw = parse_gateway(_run(cmd), sys.platform)
    if gw:
        return gw
    ip = local_ip()
    return ip.rsplit(".", 1)[0] + ".1" if ip else ""


def is_private(ip: str) -> bool:
    """True for home-network addresses (10.x, 172.16-31.x, 192.168.x) and carrier-shared ones (100.64-127.x)."""
    try:
        a, b = (int(x) for x in ip.split(".")[:2])
    except ValueError:
        return False
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) or (a == 100 and 64 <= b <= 127)


def natpmp_map(gateway: str, port: int, lifetime_s: int = 86400, timeout: float = 1.2,
               natpmp_port: int = NATPMP_PORT) -> int:
    """Ask the router (NAT-PMP, RFC 6886) to forward TCP `port` to this computer.
    Returns the seconds the router granted (0 = no answer or refused). Must be renewed before it runs out."""
    if not gateway or not port:
        return 0
    req = struct.pack("!BBHHHI", 0, 2, 0, port, port, lifetime_s)          # version 0, opcode 2 = map TCP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for wait in (timeout / 3, timeout * 2 / 3):                         # two tries, like the RFC's back-off
            s.settimeout(wait)
            try:
                s.sendto(req, (gateway, natpmp_port))
                data, _ = s.recvfrom(64)
            except (socket.timeout, OSError):
                continue
            if len(data) >= 16:
                _ver, op, result, _epoch, _internal, external, granted = struct.unpack("!BBHIHHI", data[:16])
                if op == 130 and result == 0 and external == port:
                    return int(granted)
                return 0                                                    # answered, but said no (or another port)
        return 0
    finally:
        s.close()
