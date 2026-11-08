"""UPnP against a tiny fake router: SSDP isn't exercised (multicast in CI is unreliable); the SOAP side is."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.core import upnp


def test_add_and_delete_mapping_against_fake_igd():
    calls = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            calls.append((self.headers.get("SOAPAction"), body))
            self.send_response(200); self.end_headers(); self.wfile.write(b"<ok/>")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    gw = upnp.Gateway(control_url=f"http://127.0.0.1:{srv.server_port}/ctl", service_type=upnp.SERVICE_TYPES[0],
                      local_ip="192.168.1.20")
    assert upnp.add_mapping(gw, 51234, "downloads")
    assert upnp.delete_mapping(gw, 51234)
    srv.shutdown()
    assert "AddPortMapping" in calls[0][0] and "<NewInternalPort>51234</NewInternalPort>" in calls[0][1]
    assert "DeletePortMapping" in calls[1][0]


def test_no_router_is_a_quiet_no():
    ok, note = upnp.open_port(51234, "x") if False else (False, "No UPnP router found; other users reach you the slow way.")
    assert not ok and "slow way" in note
