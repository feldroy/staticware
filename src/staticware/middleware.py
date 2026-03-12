"""ASGI middleware for static file serving with content-based cache busting.

Zero dependencies beyond the Python standard library. Works with any ASGI
framework: Starlette, FastAPI, Air, Litestar, Django, or raw ASGI.

    from staticware import HashedStatic, StaticRewriteMiddleware

    static = HashedStatic("static")

    # Wrap any ASGI app to rewrite /static/styles.css -> /static/styles.a1b2c3d4.css
    app = StaticRewriteMiddleware(your_app, static=static)

    # In templates:
    static.url("styles.css")  # -> /static/styles.a1b2c3d4.css
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any

# ASGI protocol types — inlined so we depend on nothing.
type Scope = dict[str, Any]
type Receive = Callable[[], Awaitable[dict[str, Any]]]
type Send = Callable[[dict[str, Any]], Awaitable[None]]
type ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class HashedStatic:
    """Serve static files with content-hashed filenames.

    Computes SHA-256 hashes of every file in ``directory`` at startup.
    Requests for hashed filenames (``styles.a1b2c3d4.css``) get
    ``Cache-Control: public, max-age=31536000, immutable``.
    Requests for original filenames still work, without aggressive caching.

    This is a mountable ASGI app *and* a URL resolver::

        static = HashedStatic("static")

        # Mount it however your framework mounts sub-apps:
        app.mount("/static", static)

        # Resolve URLs:
        static.url("styles.css")       # /static/styles.a1b2c3d4.css
        static.url("images/logo.png")  # /static/images/logo.7e4f9a01.png
    """

    def __init__(
        self,
        directory: str | Path,
        *,
        prefix: str = "/static",
        hash_length: int = 8,
    ) -> None:
        self.directory = Path(directory).resolve()
        self.prefix = prefix.rstrip("/")
        self.hash_length = hash_length

        # original relative path -> hashed relative path
        self.file_map: dict[str, str] = {}
        # hashed relative path -> original relative path
        self._reverse: dict[str, str] = {}

        self._hash_files()

    def _hash_files(self) -> None:
        """Walk directory and build the hash map for every file."""
        if not self.directory.exists():
            return

        for file_path in self.directory.rglob("*"):
            if not file_path.is_file():
                continue
            if not file_path.resolve().is_relative_to(self.directory):
                continue

            relative = file_path.relative_to(self.directory).as_posix()
            content = file_path.read_bytes()
            hash_val = hashlib.sha256(content).hexdigest()[: self.hash_length]

            # styles.css -> styles.a1b2c3d4.css
            # Makefile -> Makefile.a1b2c3d4
            # .gitignore -> .gitignore.a1b2c3d4
            name = file_path.name
            dot = name.rfind(".")
            if dot > 0:
                hashed_name = f"{name[:dot]}.{hash_val}{name[dot:]}"
            else:
                hashed_name = f"{name}.{hash_val}"
            parent = str(Path(relative).parent)
            if parent != ".":
                hashed = f"{parent}/{hashed_name}"
            else:
                hashed = hashed_name

            self.file_map[relative] = hashed
            self._reverse[hashed] = relative

    def url(self, path: str) -> str:
        """Return the cache-busted URL for a static file path.

        Unknown paths are returned unchanged (with the prefix).
        """
        path = path.lstrip("/")
        hashed = self.file_map.get(path, path)
        return f"{self.prefix}/{hashed}"

    # ── ASGI app ────────────────────────────────────────────────────────

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve a static file. Mount this under the prefix in your framework."""
        if scope["type"] != "http":
            return

        request_path: str = scope["path"]
        if not request_path.startswith(self.prefix + "/"):
            await _send_text(send, 404, b"Not Found")
            return

        relative_path = request_path[len(self.prefix) + 1 :]

        # Hashed filename — serve with immutable caching
        original_path = self._reverse.get(relative_path)
        if original_path:
            file_path = (self.directory / original_path).resolve()
            if file_path.is_relative_to(self.directory) and file_path.exists():
                await _send_file(
                    send,
                    file_path,
                    extra_headers=[
                        (b"cache-control", b"public, max-age=31536000, immutable"),
                    ],
                )
                return

        # Original filename — serve without aggressive caching
        file_path = (self.directory / relative_path).resolve()
        if not file_path.is_relative_to(self.directory):
            await _send_text(send, 404, b"Not Found")
            return
        if file_path.exists() and file_path.is_file():
            await _send_file(send, file_path)
            return

        await _send_text(send, 404, b"Not Found")


class StaticRewriteMiddleware:
    """ASGI middleware that rewrites static paths in HTML responses.

    Wraps any ASGI app. When the response content-type is ``text/html``,
    rewrites occurrences of ``/static/styles.css`` to their hashed
    equivalents. Non-HTML responses pass through untouched.

    Works with any templating system, component library, or hand-written
    HTML — no template function needed (though ``static.url()`` is there
    if you want it).

        app = StaticRewriteMiddleware(app, static=static)
    """

    def __init__(self, app: ASGIApp, *, static: HashedStatic) -> None:
        self.app = app
        self.static = static
        escaped = re.escape(static.prefix)
        self._pattern = re.compile(escaped + r"/([^\"'>\s)#?]+)")

    def _replace(self, match: re.Match[str]) -> str:
        path = match.group(1)
        if path in self.static.file_map:
            return f"{self.static.prefix}/{self.static.file_map[path]}"
        return match.group(0)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_start: dict[str, Any] | None = None
        body_parts: list[bytes] = []
        is_html = False

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal response_start, is_html

            if message["type"] == "http.response.start":
                response_start = message
                headers = dict(message.get("headers", []))
                content_type = headers.get(b"content-type", b"").decode("latin-1")
                is_html = "text/html" in content_type
                if not is_html:
                    # Not HTML — send the start immediately and short-circuit.
                    await send(message)
                return

            if message["type"] == "http.response.body":
                if response_start is None:
                    raise RuntimeError(
                        "http.response.body received before http.response.start"
                    )
                if not is_html:
                    await send(message)
                    return

                body = message.get("body", b"")
                more_body = message.get("more_body", False)
                body_parts.append(body)

                if not more_body:
                    full_body = b"".join(body_parts)
                    try:
                        text = full_body.decode("utf-8")
                        text = self._pattern.sub(self._replace, text)
                        full_body = text.encode("utf-8")
                    except UnicodeDecodeError:
                        pass

                    if response_start is None:
                        raise RuntimeError(
                            "http.response.body received before http.response.start"
                        )
                    new_headers = [
                        (k, str(len(full_body)).encode("latin-1"))
                        if k == b"content-length"
                        else (k, v)
                        for k, v in response_start.get("headers", [])
                    ]
                    response_start["headers"] = new_headers
                    await send(response_start)
                    await send({"type": "http.response.body", "body": full_body})
                return

        await self.app(scope, receive, send_wrapper)


# ── Raw ASGI helpers ────────────────────────────────────────────────────


async def _send_file(
    send: Send,
    path: Path,
    *,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    """Send a file as a raw ASGI response."""
    content = path.read_bytes()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", content_type.encode("latin-1")),
        (b"content-length", str(len(content)).encode("latin-1")),
    ]
    if extra_headers:
        headers.extend(extra_headers)

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": headers,
    })
    await send({
        "type": "http.response.body",
        "body": content,
    })


async def _send_text(send: Send, status: int, body: bytes) -> None:
    """Send a plain-text ASGI response."""
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"text/plain"),
            (b"content-length", str(len(body)).encode("latin-1")),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
    })
