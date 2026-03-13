"""Minimal Django URL configuration for ASGI integration tests."""

from django.http import HttpResponse
from django.urls import path


def html_view(request):
    """Return HTML containing a static file reference."""
    return HttpResponse(
        '<link href="/static/styles.css">',
        content_type="text/html; charset=utf-8",
    )


urlpatterns = [
    path("html/", html_view),
]
