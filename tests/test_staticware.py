"""Tests for staticware."""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from staticware import StaticFiles, StaticRewriteMiddleware


# ── Helpers ──────────────────────────────────────────────────────────────


async def receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b""}


class ResponseCollector:
    """Collect ASGI send() calls into status, headers, and body."""

    def __init__(self) -> None:
        self.status: int = 0
        self.headers: dict[bytes, bytes] = {}
        self.body: bytes = b""

    async def __call__(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = dict(message.get("headers", []))
        elif message["type"] == "http.response.body":
            self.body += message.get("body", b"")

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")


def make_scope(path: str) -> dict[str, Any]:
    return {"type": "http", "path": path, "method": "GET"}


def expected_hash(content: bytes, length: int = 8) -> str:
    return hashlib.sha256(content).hexdigest()[:length]


# ── StaticFiles: hashing and url() ──────────────────────────────────────


@pytest.fixture()
def static_dir(tmp_path: Path) -> Path:
    d = tmp_path / "static"
    d.mkdir()
    (d / "styles.css").write_text("body { color: red; }")
    sub = d / "images"
    sub.mkdir()
    (sub / "logo.png").write_bytes(b"\x89PNG fake image data")
    return d


@pytest.fixture()
def static(static_dir: Path) -> StaticFiles:
    return StaticFiles(static_dir)


def test_file_map_contains_all_files(static: StaticFiles, static_dir: Path) -> None:
    assert "styles.css" in static.file_map
    assert "images/logo.png" in static.file_map


def test_hash_is_correct(static: StaticFiles, static_dir: Path) -> None:
    css_content = (static_dir / "styles.css").read_bytes()
    h = expected_hash(css_content)
    assert static.file_map["styles.css"] == f"styles.{h}.css"


def test_hash_in_subdirectory(static: StaticFiles, static_dir: Path) -> None:
    png_content = (static_dir / "images" / "logo.png").read_bytes()
    h = expected_hash(png_content)
    assert static.file_map["images/logo.png"] == f"images/logo.{h}.png"


def test_url_returns_hashed_path(static: StaticFiles) -> None:
    url = static.url("styles.css")
    assert url.startswith("/static/styles.")
    assert url.endswith(".css")
    assert url != "/static/styles.css"


def test_url_unknown_file_returns_unchanged(static: StaticFiles) -> None:
    assert static.url("nonexistent.js") == "/static/nonexistent.js"


def test_url_strips_leading_slash(static: StaticFiles) -> None:
    assert static.url("/styles.css") == static.url("styles.css")


def test_custom_prefix(static_dir: Path) -> None:
    s = StaticFiles(static_dir, prefix="/assets")
    assert s.url("styles.css").startswith("/assets/")


def test_custom_hash_length(static_dir: Path) -> None:
    s = StaticFiles(static_dir, hash_length=4)
    url = s.url("styles.css")
    # /static/styles.XXXX.css — 4-char hash
    stem = url.split("/")[-1]  # styles.XXXX.css
    hash_part = stem.split(".")[1]
    assert len(hash_part) == 4


def test_nonexistent_directory(tmp_path: Path) -> None:
    s = StaticFiles(tmp_path / "nope")
    assert s.file_map == {}


def test_symlinks_outside_directory_excluded(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret data")
    (static_dir / "link.txt").symlink_to(outside)
    s = StaticFiles(static_dir)
    assert "link.txt" not in s.file_map


# ── StaticFiles: ASGI serving ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_serve_original_filename(static: StaticFiles, static_dir: Path) -> None:
    resp = ResponseCollector()
    await static(make_scope("/static/styles.css"), receive, resp)
    assert resp.status == 200
    assert resp.text == "body { color: red; }"
    assert b"cache-control" not in resp.headers


@pytest.mark.asyncio
async def test_serve_hashed_filename_with_immutable_cache(static: StaticFiles) -> None:
    hashed_name = static.file_map["styles.css"]
    resp = ResponseCollector()
    await static(make_scope(f"/static/{hashed_name}"), receive, resp)
    assert resp.status == 200
    assert resp.text == "body { color: red; }"
    assert resp.headers[b"cache-control"] == b"public, max-age=31536000, immutable"


@pytest.mark.asyncio
async def test_serve_404_for_missing_file(static: StaticFiles) -> None:
    resp = ResponseCollector()
    await static(make_scope("/static/nope.css"), receive, resp)
    assert resp.status == 404


@pytest.mark.asyncio
async def test_serve_404_outside_prefix(static: StaticFiles) -> None:
    resp = ResponseCollector()
    await static(make_scope("/other/styles.css"), receive, resp)
    assert resp.status == 404


@pytest.mark.asyncio
async def test_path_traversal_rejected(static: StaticFiles) -> None:
    resp = ResponseCollector()
    await static(make_scope("/static/../../etc/passwd"), receive, resp)
    assert resp.status == 404


@pytest.mark.asyncio
async def test_non_http_scope_ignored(static: StaticFiles) -> None:
    """WebSocket and lifespan scopes should be silently ignored."""
    resp = ResponseCollector()
    await static({"type": "websocket", "path": "/static/styles.css"}, receive, resp)
    assert resp.status == 0  # send was never called


@pytest.mark.asyncio
async def test_serve_subdirectory_file(static: StaticFiles) -> None:
    resp = ResponseCollector()
    await static(make_scope("/static/images/logo.png"), receive, resp)
    assert resp.status == 200
    assert resp.body == b"\x89PNG fake image data"


@pytest.mark.asyncio
async def test_content_type_header(static: StaticFiles) -> None:
    resp = ResponseCollector()
    await static(make_scope("/static/styles.css"), receive, resp)
    assert b"text/css" in resp.headers[b"content-type"]


# ── StaticRewriteMiddleware ─────────────────────────────────────────────


def make_html_app(html: str):
    """Create a dummy ASGI app that returns the given HTML."""
    body = html.encode("utf-8")

    async def app(scope: dict, receive: Any, send: Any) -> None:
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/html; charset=utf-8"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    return app


def make_json_app(data: bytes):
    """Create a dummy ASGI app that returns JSON."""

    async def app(scope: dict, receive: Any, send: Any) -> None:
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(data)).encode("latin-1")),
            ],
        })
        await send({"type": "http.response.body", "body": data})

    return app


@pytest.mark.asyncio
async def test_rewrite_html_response(static: StaticFiles) -> None:
    html = '<link href="/static/styles.css">'
    app = StaticRewriteMiddleware(make_html_app(html), static=static)
    resp = ResponseCollector()
    await app(make_scope("/"), receive, resp)

    hashed = static.file_map["styles.css"]
    assert f"/static/{hashed}" in resp.text
    assert "/static/styles.css" not in resp.text


@pytest.mark.asyncio
async def test_rewrite_updates_content_length(static: StaticFiles) -> None:
    html = '<link href="/static/styles.css">'
    app = StaticRewriteMiddleware(make_html_app(html), static=static)
    resp = ResponseCollector()
    await app(make_scope("/"), receive, resp)

    declared_length = int(resp.headers[b"content-length"].decode())
    assert declared_length == len(resp.body)


@pytest.mark.asyncio
async def test_rewrite_leaves_unknown_paths_alone(static: StaticFiles) -> None:
    html = '<script src="/static/app.js"></script>'
    app = StaticRewriteMiddleware(make_html_app(html), static=static)
    resp = ResponseCollector()
    await app(make_scope("/"), receive, resp)
    assert "/static/app.js" in resp.text


@pytest.mark.asyncio
async def test_non_html_passes_through(static: StaticFiles) -> None:
    data = b'{"path": "/static/styles.css"}'
    app = StaticRewriteMiddleware(make_json_app(data), static=static)
    resp = ResponseCollector()
    await app(make_scope("/api/data"), receive, resp)
    assert resp.body == data


@pytest.mark.asyncio
async def test_rewrite_multiple_paths(static: StaticFiles) -> None:
    html = '<link href="/static/styles.css"><img src="/static/images/logo.png">'
    app = StaticRewriteMiddleware(make_html_app(html), static=static)
    resp = ResponseCollector()
    await app(make_scope("/"), receive, resp)

    assert f"/static/{static.file_map['styles.css']}" in resp.text
    assert f"/static/{static.file_map['images/logo.png']}" in resp.text


@pytest.mark.asyncio
async def test_rewrite_non_http_passes_through(static: StaticFiles) -> None:
    """Non-HTTP scopes are forwarded to the wrapped app without rewriting."""
    calls: list[str] = []

    async def ws_app(scope: dict, receive: Any, send: Any) -> None:
        calls.append(scope["type"])

    app = StaticRewriteMiddleware(ws_app, static=static)
    await app({"type": "websocket", "path": "/"}, receive, ResponseCollector())
    assert calls == ["websocket"]
