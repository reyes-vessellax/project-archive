"""Open the engine's listening port on the router with UPnP (IGD), so other users can deliver search
results and files to us directly. Pure standard library: SSDP discovery, fetch the device description,
call AddPortMapping on the WAN connection service. Everything here is best-effort and never raises
out: no router, no UPnP, or a refusal just means "not open", and the engine still works through the
server's indirect route (slower, and some results never arrive).
"""
from __future__ import annotations

import re
import socket
import time
from dataclasses import dataclass
from urllib import parse, request

SSDP_ADDR, SSDP_PORT = "239.255.255.250", 1900
SERVICE_TYPES = ("urn:schemas-upnp-org:service:WANIPConnection:1", "urn:schemas-upnp-org:service:WANIPConnection:2",
                 "urn:schemas-upnp-org:service:WANPPPConnection:1")


@dataclass
class Gateway:
    control_url: str
    service_type: str
    local_ip: str


def _local_ip_towards(host: str) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def discover(timeout: float = 2.5) -> Gateway | None:
    """Find the first Internet Gateway Device that offers a WAN connection service."""
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\n"
           "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n").encode()
    locations: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.settimeout(timeout)
        s.sendto(msg, (SSDP_ADDR, SSDP_PORT))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                break
            m = re.search(rb"(?im)^location:\s*(\S+)", data)
            if m:
                loc = m.group(1).decode(errors="replace")
                if _local_url(loc, addr[0]) and loc not in locations:     # only the device that answered, on the LAN
                    locations.append(loc)
        s.close()
    except OSError:
        return None
    for loc in locations:
        gw = _gateway_from(loc)
        if gw:
            return gw
    return None


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None                                   # a router never needs to send us elsewhere


_OPENER = request.build_opener(_NoRedirect)


def _local_url(url: str, host_must_be: str = "") -> bool:
    """A plain http(s) URL on a private LAN address (and, if given, on the device that answered). Anything else
    a device on the network announces is ignored: it can't make DigMart call other hosts."""
    import ipaddress
    try:
        u = parse.urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False
        ip = ipaddress.ip_address(u.hostname)
    except ValueError:
        return False
    if not (ip.is_private and not ip.is_loopback):
        return False
    return not host_must_be or u.hostname == host_must_be


def _gateway_from(location: str) -> Gateway | None:
    try:
        with _OPENER.open(location, timeout=3) as r:
            xml = r.read().decode(errors="replace")
    except Exception:
        return None
    for st in SERVICE_TYPES:
        m = re.search(r"<serviceType>\s*" + re.escape(st) + r"\s*</serviceType>.*?<controlURL>\s*(\S+?)\s*</controlURL>",
                      xml, re.S)
        if m:
            control = parse.urljoin(location, m.group(1))
            host = parse.urlparse(location).hostname or ""
            if not _local_url(control, host):
                return None                           # the control URL must be on the same router
            try:
                local_ip = _local_ip_towards(host)
            except OSError:
                return None
            return Gateway(control_url=control, service_type=st, local_ip=local_ip)
    return None


def _soap(gw: Gateway, action: str, args: dict[str, str]) -> tuple[int, str]:
    body = "".join(f"<{k}>{v}</{k}>" for k, v in args.items())
    env = (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
           f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
           f'<u:{action} xmlns:u="{gw.service_type}">{body}</u:{action}></s:Body></s:Envelope>').encode()
    req = request.Request(gw.control_url, data=env, method="POST", headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{gw.service_type}#{action}"'})
    try:
        with _OPENER.open(req, timeout=5) as r:
            return r.status, r.read().decode(errors="replace")
    except request.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return 0, str(e)


def add_mapping(gw: Gateway, port: int, description: str, lease_s: int = 0) -> bool:
    status, text = _soap(gw, "AddPortMapping", {
        "NewRemoteHost": "", "NewExternalPort": str(port), "NewProtocol": "TCP", "NewInternalPort": str(port),
        "NewInternalClient": gw.local_ip, "NewEnabled": "1", "NewPortMappingDescription": description,
        "NewLeaseDuration": str(lease_s)})
    if status == 200:
        return True
    # some routers refuse permanent leases (error 725): try a day
    if lease_s == 0 and "725" in text:
        return add_mapping(gw, port, description, lease_s=86400)
    return False


def delete_mapping(gw: Gateway, port: int) -> bool:
    status, _ = _soap(gw, "DeletePortMapping", {"NewRemoteHost": "", "NewExternalPort": str(port), "NewProtocol": "TCP"})
    return status == 200


def open_port(port: int, description: str) -> tuple[bool, str]:
    """One call: discover + map. Returns (opened, plain-English note)."""
    ok, note, _why = open_port_why(port, description)
    return ok, note


def open_port_why(port: int, description: str) -> tuple[bool, str, str]:
    """Like open_port, plus a reason the Connection panel can act on: open | no_router | refused."""
    gw = discover()
    if gw is None:
        return False, "No UPnP router found; other users reach you the slow way.", "no_router"
    if add_mapping(gw, port, description):
        return True, f"Port {port} is open on your router.", "open"
    return False, f"Your router refused to open port {port}; other users reach you the slow way.", "refused"


def close_port(port: int) -> bool:
    """Remove a mapping we made earlier (after the user changes the port). Best effort."""
    gw = discover(timeout=1.5)
    return bool(gw and delete_mapping(gw, port))
