"""Tests for staticware.

Async test detection:
    pytest-asyncio is configured with asyncio_mode = "auto" in pyproject.toml.
    This means any test written as ``async def`` automatically runs on an event
    loop. Regular ``def`` tests run normally without one.

    Use ``async def`` for tests that call ASGI apps (they are async callables).
    Use plain ``def`` for tests that only exercise sync APIs like HashedStatic()
    construction, url(), and file_map lookups.

    Do NOT write ``async def`` for a test that has no await in its body. It will
    still pass, but it runs on an event loop for no reason and misleads readers
    into thinking the test exercises async behavior.
"""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from staticware import HashedStatic, StaticRewriteMiddleware

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


# ── HashedStatic: hashing and url() ──────────────────────────────────────


def test_file_map_contains_all_files(static: HashedStatic, static_dir: Path) -> None:
    assert "styles.css" in static.file_map
    assert "images/logo.png" in static.file_map


def test_hash_is_correct(static: HashedStatic, static_dir: Path) -> None:
    css_content = (static_dir / "styles.css").read_bytes()
    h = expected_hash(css_content)
    assert static.file_map["styles.css"] == f"styles.{h}.css"


def test_hash_in_subdirectory(static: HashedStatic, static_dir: Path) -> None:
    png_content = (static_dir / "images" / "logo.png").read_bytes()
    h = expected_hash(png_content)
    assert static.file_map["images/logo.png"] == f"images/logo.{h}.png"


def test_url_returns_hashed_path(static: HashedStatic) -> None:
    url = static.url("styles.css")
    assert url.startswith("/static/styles.")
    assert url.endswith(".css")
    assert url != "/static/styles.css"


def test_url_unknown_file_returns_unchanged(static: HashedStatic) -> None:
    assert static.url("nonexistent.js") == "/static/nonexistent.js"


def test_url_strips_leading_slash(static: HashedStatic) -> None:
    assert static.url("/styles.css") == static.url("styles.css")


def test_custom_prefix(static_dir: Path) -> None:
    s = HashedStatic(static_dir, prefix="/assets")
    assert s.url("styles.css").startswith("/assets/")


def test_custom_hash_length(static_dir: Path) -> None:
    s = HashedStatic(static_dir, hash_length=4)
    url = s.url("styles.css")
    # /static/styles.XXXX.css — 4-char hash
    stem = url.split("/")[-1]  # styles.XXXX.css
    hash_part = stem.split(".")[1]
    assert len(hash_part) == 4


def test_nonexistent_directory(tmp_path: Path) -> None:
    s = HashedStatic(tmp_path / "nope")
    assert s.file_map == {}


def test_symlinks_outside_directory_excluded(tmp_path: Path) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret data")
    (static_dir / "link.txt").symlink_to(outside)
    s = HashedStatic(static_dir)
    assert "link.txt" not in s.file_map


def test_extensionless_file(tmp_path: Path) -> None:
    d = tmp_path / "static"
    d.mkdir()
    (d / "Makefile").write_text("all: build")
    s = HashedStatic(d)
    h = expected_hash(b"all: build")
    assert s.file_map["Makefile"] == f"Makefile.{h}"


def test_dotfile(tmp_path: Path) -> None:
    d = tmp_path / "static"
    d.mkdir()
    (d / ".gitignore").write_text("*.pyc")
    s = HashedStatic(d)
    h = expected_hash(b"*.pyc")
    assert s.file_map[".gitignore"] == f".gitignore.{h}"


def test_multi_dot_filename(tmp_path: Path) -> None:
    d = tmp_path / "static"
    d.mkdir()
    (d / "jquery.min.js").write_text("js code")
    s = HashedStatic(d)
    h = expected_hash(b"js code")
    assert s.file_map["jquery.min.js"] == f"jquery.min.{h}.js"


# ── HashedStatic: ASGI serving ───────────────────────────────────────────


async def test_serve_original_filename(static: HashedStatic, static_dir: Path) -> None:
    resp = ResponseCollector()
    await static(make_scope("/static/styles.css"), receive, resp)
    assert resp.status == 200
    assert resp.text == "body { color: red; }"
    assert b"cache-control" not in resp.headers


async def test_serve_hashed_filename_with_immutable_cache(static: HashedStatic) -> None:
    hashed_name = static.file_map["styles.css"]
    resp = ResponseCollector()
    await static(make_scope(f"/static/{hashed_name}"), receive, resp)
    assert resp.status == 200
    assert resp.text == "body { color: red; }"
    assert resp.headers[b"cache-control"] == b"public, max-age=31536000, immutable"


async def test_serve_404_for_missing_file(static: HashedStatic) -> None:
    resp = ResponseCollector()
    await static(make_scope("/static/nope.css"), receive, resp)
    assert resp.status == 404


async def test_serve_404_outside_prefix(static: HashedStatic) -> None:
    resp = ResponseCollector()
    await static(make_scope("/other/styles.css"), receive, resp)
    assert resp.status == 404


async def test_path_traversal_rejected(static: HashedStatic) -> None:
    resp = ResponseCollector()
    await static(make_scope("/static/../../etc/passwd"), receive, resp)
    assert resp.status == 404


async def test_non_http_scope_ignored(static: HashedStatic) -> None:
    """WebSocket and lifespan scopes should be silently ignored."""
    resp = ResponseCollector()
    await static({"type": "websocket", "path": "/static/styles.css"}, receive, resp)
    assert resp.status == 0  # send was never called


async def test_serve_subdirectory_file(static: HashedStatic) -> None:
    resp = ResponseCollector()
    await static(make_scope("/static/images/logo.png"), receive, resp)
    assert resp.status == 200
    assert resp.body == b"\x89PNG fake image data"


async def test_content_type_header(static: HashedStatic) -> None:
    resp = ResponseCollector()
    await static(make_scope("/static/styles.css"), receive, resp)
    assert b"text/css" in resp.headers[b"content-type"]


# ── StaticRewriteMiddleware ─────────────────────────────────────────────


def make_html_app(html: str):
    """Create a dummy ASGI app that returns the given HTML."""
    body = html.encode("utf-8")

    async def app(scope: dict, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return app


def make_json_app(data: bytes):
    """Create a dummy ASGI app that returns JSON."""

    async def app(scope: dict, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(data)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": data})

    return app


async def test_rewrite_html_response(static: HashedStatic) -> None:
    html = '<link href="/static/styles.css">'
    app = StaticRewriteMiddleware(make_html_app(html), static=static)
    resp = ResponseCollector()
    await app(make_scope("/"), receive, resp)

    hashed = static.file_map["styles.css"]
    assert f"/static/{hashed}" in resp.text
    assert "/static/styles.css" not in resp.text


async def test_rewrite_updates_content_length(static: HashedStatic) -> None:
    html = '<link href="/static/styles.css">'
    app = StaticRewriteMiddleware(make_html_app(html), static=static)
    resp = ResponseCollector()
    await app(make_scope("/"), receive, resp)

    declared_length = int(resp.headers[b"content-length"].decode())
    assert declared_length == len(resp.body)


async def test_rewrite_leaves_unknown_paths_alone(static: HashedStatic) -> None:
    html = '<script src="/static/app.js"></script>'
    app = StaticRewriteMiddleware(make_html_app(html), static=static)
    resp = ResponseCollector()
    await app(make_scope("/"), receive, resp)
    assert "/static/app.js" in resp.text


async def test_non_html_passes_through(static: HashedStatic) -> None:
    data = b'{"path": "/static/styles.css"}'
    app = StaticRewriteMiddleware(make_json_app(data), static=static)
    resp = ResponseCollector()
    await app(make_scope("/api/data"), receive, resp)
    assert resp.body == data


async def test_rewrite_multiple_paths(static: HashedStatic) -> None:
    html = '<link href="/static/styles.css"><img src="/static/images/logo.png">'
    app = StaticRewriteMiddleware(make_html_app(html), static=static)
    resp = ResponseCollector()
    await app(make_scope("/"), receive, resp)

    assert f"/static/{static.file_map['styles.css']}" in resp.text
    assert f"/static/{static.file_map['images/logo.png']}" in resp.text


async def test_rewrite_non_http_passes_through(static: HashedStatic) -> None:
    """Non-HTTP scopes are forwarded to the wrapped app without rewriting."""
    calls: list[str] = []

    async def ws_app(scope: dict, receive: Any, send: Any) -> None:
        calls.append(scope["type"])

    app = StaticRewriteMiddleware(ws_app, static=static)
    await app({"type": "websocket", "path": "/"}, receive, ResponseCollector())
    assert calls == ["websocket"]


async def test_rewrite_raises_runtime_error_on_body_before_start(
    static: HashedStatic,
) -> None:
    """Middleware should raise RuntimeError if app sends body before start.

    An ASGI app that sends http.response.body without first sending
    http.response.start is violating the protocol.  The middleware must
    detect this and raise RuntimeError (not AssertionError, which would
    be stripped by python -O).
    """

    async def broken_app(scope: dict, receive: Any, send: Any) -> None:
        # Skip http.response.start entirely — straight to body.
        await send(
            {
                "type": "http.response.body",
                "body": b"<html>oops</html>",
            }
        )

    app = StaticRewriteMiddleware(broken_app, static=static)
    with pytest.raises(RuntimeError):
        await app(make_scope("/"), receive, ResponseCollector())


async def test_rewrite_streaming_html_response(static: HashedStatic) -> None:
    """Middleware rewrites static paths even when the body arrives in multiple chunks."""
    chunk1 = b'<link href="/static/'
    chunk2 = b'styles.css">'

    async def streaming_app(scope: dict, receive: Any, send: Any) -> None:
        total = len(chunk1) + len(chunk2)
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"content-length", str(total).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": chunk1, "more_body": True})
        await send({"type": "http.response.body", "body": chunk2, "more_body": False})

    app = StaticRewriteMiddleware(streaming_app, static=static)
    resp = ResponseCollector()
    await app(make_scope("/"), receive, resp)

    hashed = static.file_map["styles.css"]
    assert f"/static/{hashed}" in resp.text
    assert "/static/styles.css" not in resp.text


async def test_serve_prefix_only_returns_404(static: HashedStatic) -> None:
    """Requesting /static or /static/ with no filename returns 404."""
    # /static with no trailing slash
    resp_no_slash = ResponseCollector()
    await static(make_scope("/static"), receive, resp_no_slash)
    assert resp_no_slash.status == 404

    # /static/ with trailing slash but no filename
    resp_slash = ResponseCollector()
    await static(make_scope("/static/"), receive, resp_slash)
    assert resp_slash.status == 404


async def test_rewrite_non_utf8_html_passes_through(static: HashedStatic) -> None:
    """HTML response with non-UTF-8 bytes passes through unchanged."""
    raw_body = b"<html>\x80\x81\x82 not valid utf-8</html>"

    async def bad_encoding_app(scope: dict, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"content-length", str(len(raw_body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": raw_body})

    app = StaticRewriteMiddleware(bad_encoding_app, static=static)
    resp = ResponseCollector()
    await app(make_scope("/"), receive, resp)
    assert resp.body == raw_body


# ── HashedStatic: framework mount compatibility ───────────────────────


def make_mount_scope(path: str, *, root_path: str = "") -> dict[str, Any]:
    """Like make_scope but accepts root_path for framework-mount simulation."""
    return {"type": "http", "path": path, "root_path": root_path, "method": "GET"}


async def test_serve_with_root_path_scope(static: HashedStatic, static_dir: Path) -> None:
    """Starlette-style mount: root_path set, path still includes the prefix.

    Starlette sets scope["root_path"] = "/static" and leaves
    scope["path"] = "/static/styles.css".  The current code happens to
    pass because the prefix check still matches, but we need this test
    to lock in the expected behavior when root_path is present.
    """
    resp = ResponseCollector()
    scope = make_mount_scope("/static/styles.css", root_path="/static")
    await static(scope, receive, resp)
    assert resp.status == 200
    assert resp.text == "body { color: red; }"


async def test_serve_with_stripped_path(static: HashedStatic, static_dir: Path) -> None:
    """Litestar-style mount: framework strips the prefix from scope["path"].

    The sub-app sees scope["root_path"] = "/static" and
    scope["path"] = "/styles.css".  The current code 404s because
    "/styles.css" does not start with "/static/".
    """
    resp = ResponseCollector()
    scope = make_mount_scope("/styles.css", root_path="/static")
    await static(scope, receive, resp)
    assert resp.status == 200
    assert resp.text == "body { color: red; }"
    assert b"cache-control" not in resp.headers


async def test_serve_hashed_with_stripped_path(static: HashedStatic) -> None:
    """Litestar-style mount with a hashed filename request.

    scope["root_path"] = "/static", scope["path"] = "/styles.<hash>.css".
    Should serve the file with immutable cache headers but will 404
    against current code.
    """
    hashed_name = static.file_map["styles.css"]
    resp = ResponseCollector()
    scope = make_mount_scope(f"/{hashed_name}", root_path="/static")
    await static(scope, receive, resp)
    assert resp.status == 200
    assert resp.text == "body { color: red; }"
    assert resp.headers[b"cache-control"] == b"public, max-age=31536000, immutable"


async def test_serve_with_mismatched_mount_and_prefix(static_dir: Path) -> None:
    """Mount prefix differs from HashedStatic prefix.

    HashedStatic is constructed with prefix="/assets" but the framework
    mounts it at /static, so root_path="/static" and
    path="/static/styles.css".  The current code 404s because the prefix
    check looks for "/assets/" which does not match "/static/...".
    """
    static = HashedStatic(static_dir, prefix="/assets")
    resp = ResponseCollector()
    scope = make_mount_scope("/static/styles.css", root_path="/static")
    await static(scope, receive, resp)
    assert resp.status == 200
    assert resp.text == "body { color: red; }"


# ── HashedStatic: ETag and conditional requests ──────────────────────


def make_scope_with_headers(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, Any]:
    scope: dict[str, Any] = {"type": "http", "path": path, "method": "GET"}
    if headers:
        scope["headers"] = headers
    return scope


async def test_etag_on_unhashed_response(static: HashedStatic, static_dir: Path) -> None:
    """Original filename response includes an ETag header with the content hash."""
    resp = ResponseCollector()
    await static(make_scope("/static/styles.css"), receive, resp)
    assert resp.status == 200

    css_content = (static_dir / "styles.css").read_bytes()
    h = expected_hash(css_content)
    assert b"etag" in resp.headers, "Response should include an etag header"
    assert resp.headers[b"etag"] == f'"{h}"'.encode("latin-1")


async def test_conditional_request_returns_304(static: HashedStatic, static_dir: Path) -> None:
    """If-None-Match with matching ETag returns 304 and empty body."""
    css_content = (static_dir / "styles.css").read_bytes()
    h = expected_hash(css_content)
    etag_value = f'"{h}"'.encode("latin-1")

    scope = make_scope_with_headers(
        "/static/styles.css",
        headers=[(b"if-none-match", etag_value)],
    )
    resp = ResponseCollector()
    await static(scope, receive, resp)
    assert resp.status == 304
    assert resp.body == b""


async def test_conditional_request_mismatched_etag_returns_200(
    static: HashedStatic,
) -> None:
    """If-None-Match with wrong ETag returns 200 with full body."""
    scope = make_scope_with_headers(
        "/static/styles.css",
        headers=[(b"if-none-match", b'"wronghash"')],
    )
    resp = ResponseCollector()
    await static(scope, receive, resp)
    assert resp.status == 200
    assert resp.text == "body { color: red; }"


async def test_hashed_url_no_etag(static: HashedStatic) -> None:
    """Hashed URL responses use immutable caching and should not include an ETag."""
    hashed_name = static.file_map["styles.css"]
    resp = ResponseCollector()
    await static(make_scope(f"/static/{hashed_name}"), receive, resp)
    assert resp.status == 200
    assert b"etag" not in resp.headers, "Hashed URL should not include an etag header"
