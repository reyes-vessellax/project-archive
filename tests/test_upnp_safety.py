"""Audit (Medium): a device on the LAN chose the URL DigMart fetched and posted to. Only private LAN addresses on
the device that answered are used now."""
from app.core import upnp


def test_only_lan_urls_on_the_answering_device():
    assert upnp._local_url("http://192.168.1.1:5000/rootDesc.xml", "192.168.1.1")
    assert not upnp._local_url("http://192.168.1.1:5000/x.xml", "192.168.1.50")        # not the device that answered
    assert not upnp._local_url("http://8.8.8.8/x.xml")                                  # internet host
    assert not upnp._local_url("http://127.0.0.1:5030/api/v0/x")                         # our own engine
    assert not upnp._local_url("file:///etc/passwd")
    assert not upnp._local_url("http://router.example.com/x")                            # names, not addresses


def test_control_url_elsewhere_is_refused(monkeypatch):
    xml = ("<root><serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>"
           "<controlURL>http://10.0.0.99/ctl</controlURL></root>")

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return xml.encode()
    monkeypatch.setattr(upnp._OPENER, "open", lambda *a, **k: R())
    assert upnp._gateway_from("http://192.168.1.1/rootDesc.xml") is None
