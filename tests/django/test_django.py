"""Tests for the Django integration of staticware.

Async test detection:
    pytest-asyncio is configured with asyncio_mode = "auto" in pyproject.toml.
    Use ``async def`` for tests that call ASGI apps (they are async callables).
    Use plain ``def`` for tests that only exercise sync APIs.
"""

from pathlib import Path
from typing import Any

import pytest
from django.test import override_settings

from staticware import HashedStatic

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


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_get_static_cache():
    """Clear the get_static() singleton between tests."""
    yield
    try:
        import staticware.contrib.django as django_mod

        if hasattr(django_mod, "_static_instance"):
            django_mod._static_instance = None
    except ImportError:
        pass


# ── get_static() tests ───────────────────────────────────────────────────


def test_get_static_returns_hashed_static_instance(static_dir: Path) -> None:
    """get_static() returns a HashedStatic instance when STATICWARE_DIRECTORY is set."""
    with override_settings(STATICWARE_DIRECTORY=str(static_dir)):
        from staticware.contrib.django import get_static

        result = get_static()
        assert isinstance(result, HashedStatic)


def test_get_static_uses_static_url_as_default_prefix(static_dir: Path) -> None:
    """When STATICWARE_PREFIX is not set but STATIC_URL is, uses STATIC_URL as prefix."""
    with override_settings(
        STATICWARE_DIRECTORY=str(static_dir),
        STATIC_URL="/assets/",
    ):
        from staticware.contrib.django import get_static

        result = get_static()
        # STATIC_URL="/assets/" should become prefix="/assets"
        assert result.prefix == "/assets"


def test_get_static_custom_prefix(static_dir: Path) -> None:
    """STATICWARE_PREFIX takes precedence over STATIC_URL."""
    with override_settings(
        STATICWARE_DIRECTORY=str(static_dir),
        STATIC_URL="/assets/",
        STATICWARE_PREFIX="/cdn",
    ):
        from staticware.contrib.django import get_static

        result = get_static()
        assert result.prefix == "/cdn"


def test_get_static_custom_hash_length(static_dir: Path) -> None:
    """STATICWARE_HASH_LENGTH is respected."""
    with override_settings(
        STATICWARE_DIRECTORY=str(static_dir),
        STATICWARE_HASH_LENGTH=4,
    ):
        from staticware.contrib.django import get_static

        result = get_static()
        assert result.hash_length == 4
        # Verify by checking an actual hashed filename
        url = result.url("styles.css")
        stem = url.split("/")[-1]  # styles.XXXX.css
        hash_part = stem.split(".")[1]
        assert len(hash_part) == 4


def test_get_static_raises_without_directory() -> None:
    """Missing STATICWARE_DIRECTORY raises ImproperlyConfigured."""
    from django.core.exceptions import ImproperlyConfigured

    with override_settings():
        from staticware.contrib.django import get_static

        with pytest.raises(ImproperlyConfigured):
            get_static()


def test_get_static_is_singleton(static_dir: Path) -> None:
    """Calling get_static() twice returns the same instance."""
    with override_settings(STATICWARE_DIRECTORY=str(static_dir)):
        from staticware.contrib.django import get_static

        first = get_static()
        second = get_static()
        assert first is second


# ── Template tag tests ───────────────────────────────────────────────────


def test_hashed_static_tag_renders_hashed_url(static_dir: Path) -> None:
    """{% hashed_static 'styles.css' %} produces the hashed URL."""
    from django.template import Context, Template

    with override_settings(STATICWARE_DIRECTORY=str(static_dir)):
        template = Template('{% load staticware_tags %}{% hashed_static "styles.css" %}')
        result = template.render(Context())

        # The result should be a hashed URL like /static/styles.a1b2c3d4.css
        assert result.startswith("/static/styles.")
        assert result.endswith(".css")
        assert result != "/static/styles.css"


def test_hashed_static_tag_unknown_file(static_dir: Path) -> None:
    """Unknown file returns path with prefix unchanged."""
    from django.template import Context, Template

    with override_settings(STATICWARE_DIRECTORY=str(static_dir)):
        template = Template('{% load staticware_tags %}{% hashed_static "nonexistent.js" %}')
        result = template.render(Context())

        assert result == "/static/nonexistent.js"


# ── ASGI integration tests ───────────────────────────────────────────────


async def test_get_asgi_application_serves_static(static_dir: Path) -> None:
    """The wrapped ASGI app serves hashed static files."""
    with override_settings(
        STATICWARE_DIRECTORY=str(static_dir),
        ROOT_URLCONF="tests.django.urls",
    ):
        from staticware.contrib.django import get_asgi_application, get_static

        app = get_asgi_application()
        static = get_static()

        hashed_name = static.file_map["styles.css"]
        resp = ResponseCollector()
        await app(make_scope(f"/static/{hashed_name}"), receive, resp)
        assert resp.status == 200
        assert resp.text == "body { color: red; }"
        assert resp.headers[b"cache-control"] == b"public, max-age=31536000, immutable"


async def test_get_asgi_application_rewrites_html(static_dir: Path) -> None:
    """The wrapped ASGI app rewrites HTML responses to use hashed URLs."""
    with override_settings(
        STATICWARE_DIRECTORY=str(static_dir),
        ROOT_URLCONF="tests.django.urls",
    ):
        from staticware.contrib.django import get_asgi_application, get_static

        app = get_asgi_application()
        static = get_static()

        # Request the Django view that returns HTML with /static/styles.css.
        # The StaticRewriteMiddleware should rewrite it to the hashed URL.
        resp = ResponseCollector()
        await app(make_scope("/html/"), receive, resp)
        assert resp.status == 200

        hashed = static.file_map["styles.css"]
        assert f"/static/{hashed}" in resp.text
        assert "/static/styles.css" not in resp.text
