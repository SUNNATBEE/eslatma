"""Standart API xato javoblari."""

import json

from aiohttp import web

from routes.api_json import json_err, json_ok


def _body_dict(resp: web.Response) -> dict:
    raw = resp.body
    assert isinstance(raw, (bytes, bytearray))
    return json.loads(raw.decode())


def test_json_err_body() -> None:
    resp = json_err("Xato matni", code="test_code", status=418)
    assert resp.status == 418
    assert _body_dict(resp) == {"ok": False, "error": "Xato matni", "code": "test_code"}


def test_json_ok_merges_fields() -> None:
    resp = json_ok(foo=1, bar="z")
    assert resp.status == 200
    assert _body_dict(resp) == {"ok": True, "foo": 1, "bar": "z"}


def test_json_ok_returns_response() -> None:
    r = json_ok()
    assert isinstance(r, web.Response)
    assert r.status == 200
