"""Thin JSON-RPC client for Odoo's external API (standard library only).

JSON-RPC rather than XML-RPC: Odoo methods that return None (e.g.
`check_access_rule`) cannot be marshalled over XML-RPC; the server then logs a
traceback for every such call.
"""
from __future__ import annotations

import itertools
import json
import urllib.request

from . import config

_ids = itertools.count(1)


class RpcError(Exception):
    """Server-side exception; str() starts with the exception class, e.g.
    'odoo.exceptions.AccessError: ...'."""

    def __init__(self, error: dict):
        data = error.get("data") or {}
        self.name = data.get("name", "")
        self.server_message = data.get("message") or error.get("message", "")
        super().__init__(f"{self.name}: {self.server_message}")


def _call(url: str, service: str, method: str, args: list):
    payload = {"jsonrpc": "2.0", "method": "call", "id": next(_ids),
               "params": {"service": service, "method": method, "args": args}}
    req = urllib.request.Request(f"{url}/jsonrpc", json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        res = json.loads(resp.read())
    if res.get("error"):
        raise RpcError(res["error"])
    return res.get("result")


class Odoo:
    """One authenticated user. All calls run with that user's access rights."""

    def __init__(self, login: str, password: str, url: str | None = None, db: str | None = None):
        self.url = url or config.URL
        self.db = db or config.DB
        self.login = login
        self.password = password
        self.uid = _call(self.url, "common", "authenticate", [self.db, login, password, {}])
        if not self.uid:
            raise RuntimeError(f"Odoo login failed for {login!r}")

    def call(self, model: str, method: str, *args, **kwargs):
        return _call(self.url, "object", "execute_kw",
                     [self.db, self.uid, self.password, model, method, list(args), kwargs])

    # kept for callers written against the XML-RPC client; JSON-RPC returns None fine
    call_void = call

    def search(self, model, domain, **kw):
        return self.call(model, "search", domain, **kw)

    def read(self, model, ids, fields):
        return self.call(model, "read", ids, fields=fields)

    def search_read(self, model, domain, fields, **kw):
        return self.call(model, "search_read", domain, fields=fields, **kw)

    def create(self, model, vals):
        return self.call(model, "create", vals)

    def write(self, model, ids, vals):
        return self.call(model, "write", ids, vals)

    def ref(self, xmlid: str) -> int:
        module, name = xmlid.split(".", 1)
        rows = self.search_read("ir.model.data", [("module", "=", module), ("name", "=", name)], ["res_id"])
        if not rows:
            raise KeyError(xmlid)
        return rows[0]["res_id"]


class _Service:
    def __init__(self, url: str, name: str):
        self._url, self._name = url, name

    def __getattr__(self, method: str):
        return lambda *args: _call(self._url, self._name, method, list(args))


def db_service(url: str | None = None):
    """Odoo's database service (list, create_database, drop)."""
    return _Service(url or config.URL, "db")
