"""Passive network evidence collection during a probe run.

While probes are being sent, we listen to every request/response the page
makes. If the wrapper site's frontend talks directly to a known provider
domain (e.g. api.deepseek.com) or uses a distinctive provider header, that is
strong evidence for which backend actually serves the chat.
"""
from urllib.parse import urlparse

from detector.fingerprint_db import all_domain_index, all_header_index


class NetworkCapture:
    """Attach to a Playwright page and record provider-relevant traffic."""

    def __init__(self, db: dict):
        self.domain_index = all_domain_index(db)
        self.header_index = all_header_index(db)
        # domain -> {request_count, header_hits: {header: count}}
        self.evidence = {}

    # ------------------------------------------------------------- helpers

    def _record_domain(self, host: str):
        host = (host or "").lower()
        for domain, key in self.domain_index.items():
            if host == domain or host.endswith("." + domain):
                entry = self.evidence.setdefault(key, {"requests": 0, "headers": {}})
                entry["requests"] += 1

    def _record_headers(self, headers: dict):
        for name, _value in headers.items():
            key_list = self.header_index.get(name.lower())
            if not key_list:
                continue
            for key in key_list:
                entry = self.evidence.setdefault(key, {"requests": 0, "headers": {}})
                entry["headers"][name.lower()] = entry["headers"].get(name.lower(), 0) + 1

    # ------------------------------------------------------------ handlers

    def on_request(self, request):
        host = urlparse(request.url).netloc.split(":")[0]
        self._record_domain(host)
        try:
            self._record_headers(request.headers)
        except Exception:
            pass

    def on_response(self, response):
        try:
            self._record_headers(response.headers)
        except Exception:
            pass

    # -------------------------------------------------------------- attach

    def attach(self, page):
        page.on("request", self.on_request)
        page.on("response", self.on_response)

    def detach(self, page):
        page.remove_listener("request", self.on_request)
        page.remove_listener("response", self.on_response)

    def summary(self) -> dict:
        """Return {model_key: evidence_dict} for models with any evidence."""
        return {k: v for k, v in self.evidence.items() if v["requests"] or v["headers"]}
