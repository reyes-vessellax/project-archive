"""HTTPS for the packaged app.

The Python bundled inside the app can't see the operating system's certificate store, so plain urllib
fails every HTTPS connection there ("couldn't reach the server"), even though it works when run from source.
Every outgoing HTTPS request goes through `urlopen` here, which verifies against certifi's CA bundle.
"""
from __future__ import annotations

import ssl
import urllib.error
import urllib.request

_ctx: ssl.SSLContext | None = None


def ssl_context() -> ssl.SSLContext:
    global _ctx
    if _ctx is None:
        try:
            import certifi
            _ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:                                   # certifi missing: fall back to the system defaults
            _ctx = ssl.create_default_context()
    return _ctx


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not str(newurl).lower().startswith("https://"):
            raise urllib.error.URLError(f"refused a redirect away from https ({newurl[:60]})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urlopen(req, timeout: float = 15.0, https_only: bool = False):
    """urllib.request.urlopen with verified HTTPS that works inside the packaged app (redirects followed).
    https_only: every redirect must stay on https too (the updater)."""
    handlers = [urllib.request.HTTPSHandler(context=ssl_context())]
    if https_only:
        handlers.append(_HttpsOnlyRedirects())
    opener = urllib.request.build_opener(*handlers)
    return opener.open(req, timeout=timeout)
