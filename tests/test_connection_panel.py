"""The Connection panel (Settings → Advanced): router lookup, NAT-PMP as the second way in, and what the panel says."""
import socket
import struct
import threading

from app.core import netinfo


def test_gateway_is_read_from_each_systems_routing_table():
    win = "Active Routes:\n          0.0.0.0          0.0.0.0      192.168.50.1    192.168.50.23     25\n"
    mac = "   route to: default\n    gateway: 10.0.0.1\n  interface: en0\n"
    lin = "default via 192.168.1.254 dev wlan0 proto dhcp metric 600\n"
    assert netinfo.parse_gateway(win, "win32") == "192.168.50.1"
    assert netinfo.parse_gateway(mac, "darwin") == "10.0.0.1"
    assert netinfo.parse_gateway(lin, "linux") == "192.168.1.254"
    assert netinfo.parse_gateway("nothing here", "win32") == ""
    assert netinfo.is_private("192.168.1.4") and netinfo.is_private("100.72.0.9") and not netinfo.is_private("8.8.8.8")


def _fake_natpmp(result: int, granted: int):
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); srv.bind(("127.0.0.1", 0)); srv.settimeout(3)
    seen = []

    def run():
        try:
            data, addr = srv.recvfrom(64)
        except socket.timeout:
            return
        ver, op, _r, internal, external, life = struct.unpack("!BBHHHI", data)
        seen.append((ver, op, internal, external, life))
        srv.sendto(struct.pack("!BBHIHHI", 0, 130, result, 1, internal, external, granted), addr)
    threading.Thread(target=run, daemon=True).start()
    return srv, seen


def test_natpmp_opens_the_port_and_reports_how_long_for():
    srv, seen = _fake_natpmp(result=0, granted=3600)
    assert netinfo.natpmp_map("127.0.0.1", 51234, natpmp_port=srv.getsockname()[1]) == 3600
    assert seen == [(0, 2, 51234, 51234, 86400)]                       # TCP map request for our port
    srv.close()


def test_natpmp_refusal_and_silence_are_a_quiet_no():
    srv, _ = _fake_natpmp(result=2, granted=0)                         # 2 = not authorised
    assert netinfo.natpmp_map("127.0.0.1", 51234, natpmp_port=srv.getsockname()[1]) == 0
    srv.close()
    dead = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); dead.bind(("127.0.0.1", 0))
    assert netinfo.natpmp_map("127.0.0.1", 51234, timeout=0.3, natpmp_port=dead.getsockname()[1]) == 0
    dead.close()
    assert netinfo.natpmp_map("", 51234) == 0


def test_service_falls_back_to_natpmp_and_schedules_a_renewal(service, monkeypatch):
    from app.core import upnp
    service.settings.listen_port, service.settings.upnp = 51234, True
    monkeypatch.setattr(upnp, "open_port_why", lambda p, d: (False, "No UPnP router found; other users reach you the slow way.", "no_router"))
    monkeypatch.setattr(netinfo, "router_ip", lambda: "192.168.1.1")
    monkeypatch.setattr(netinfo, "natpmp_map", lambda gw, port, *a, **k: 7200)
    service.open_port()
    assert service.port_open and service.port_method == "NAT-PMP" and service.port_why == "open"
    assert service.port_renew_at > 0 and not service.port_renew_due()
    monkeypatch.setattr(netinfo, "natpmp_map", lambda gw, port, *a, **k: 0)
    service.open_port()
    assert not service.port_open and service.port_why == "no_router" and not service.port_renew_due()
    service.settings.upnp = False
    service.open_port()
    assert service.port_why == "off"


def test_panel_explains_each_state_with_the_values_to_type(service, monkeypatch):
    import time
    from PySide6.QtWidgets import QApplication
    from app.ui.settings_page import SettingsPage
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(netinfo, "local_ip", lambda: "192.168.1.23")
    monkeypatch.setattr(netinfo, "router_ip", lambda: "192.168.1.1")
    service.settings.listen_port, service.settings.upnp = 51234, True
    service.port_open, service.port_why = False, "no_router"
    page = SettingsPage(service)
    page.show_section("advanced")
    assert page.conn_pill.text() == "Slow route" and "didn't answer" in page.conn_text.text()
    steps = page.conn_steps.text()
    assert "51234" in steps and "TCP" in steps and "192.168.1.23" in steps and "192.168.1.1" in steps
    assert page.port.value() == 51234 and page.router_btn.isEnabled()

    service.port_open, service.port_why, service.port_method = True, "open", "NAT-PMP"
    page._show_connection()
    assert page.conn_pill.text() == "Direct connection" and "NAT-PMP" in page.conn_text.text() and page.conn_steps.text() == ""

    # Test again runs the check off the UI thread and repaints
    def fake_check():
        service.port_open, service.port_why = False, "refused"
    monkeypatch.setattr(service, "check_port", fake_check)
    page._test_port()
    assert not page.test_btn.isEnabled()
    end = time.monotonic() + 5
    while not page.test_btn.isEnabled() and time.monotonic() < end:
        app.processEvents(); time.sleep(0.01)
    assert "said no" in page.conn_text.text() and page.test_btn.text() == "Test again"

    # a new port is saved (the main window restarts the engine on that)
    page.port.setValue(51999); page._save_settings()
    assert service.settings.listen_port == 51999
