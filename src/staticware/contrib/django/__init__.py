from __future__ import annotations

_static_instance = None


def get_static():
    """Return a singleton HashedStatic configured from Django settings.

    Reads STATICWARE_DIRECTORY (required), STATICWARE_PREFIX (optional,
    falls back to STATIC_URL then "/static"), and STATICWARE_HASH_LENGTH
    (optional, defaults to 8) from django.conf.settings.
    """
    global _static_instance

    if _static_instance is not None:
        return _static_instance

    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    from staticware import HashedStatic

    directory = getattr(settings, "STATICWARE_DIRECTORY", None)
    if directory is None:
        raise ImproperlyConfigured(
            "STATICWARE_DIRECTORY must be set in your Django settings "
            "to use staticware's Django integration."
        )

    prefix = getattr(settings, "STATICWARE_PREFIX", None)
    if prefix is None:
        static_url = getattr(settings, "STATIC_URL", None)
        if static_url is not None:
            prefix = static_url.rstrip("/")
        else:
            prefix = "/static"

    hash_length = getattr(settings, "STATICWARE_HASH_LENGTH", 8)

    _static_instance = HashedStatic(
        directory,
        prefix=prefix,
        hash_length=hash_length,
    )
    return _static_instance


def get_asgi_application():
    """Return an ASGI application that serves hashed static files and
    rewrites HTML responses from Django.

    Combines Django's ASGI app with HashedStatic file serving and
    StaticRewriteMiddleware for automatic URL rewriting.
    """
    from django.core.asgi import get_asgi_application as django_get_asgi_application

    from staticware import StaticRewriteMiddleware

    django_app = django_get_asgi_application()
    static = get_static()

    async def _normalized_django(scope, receive, send):
        """Wrap Django's ASGI app to normalize header names to lowercase.

        The ASGI spec requires lowercase header names, but Django sends
        mixed-case headers like ``Content-Type``. StaticRewriteMiddleware
        looks for ``content-type`` per the spec, so we normalize here.
        """
        async def normalizing_send(message):
            if message.get("type") == "http.response.start" and "headers" in message:
                message = {
                    **message,
                    "headers": [(k.lower(), v) for k, v in message["headers"]],
                }
            await send(message)

        await django_app(scope, receive, normalizing_send)

    wrapped = StaticRewriteMiddleware(_normalized_django, static=static)

    async def combined(scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(static.prefix + "/"):
            await static(scope, receive, send)
        else:
            import asyncio

            body_msg = await receive()
            got_body = False

            async def django_receive():
                """Return the request body once, then block until cancelled.

                Django's ASGI handler spawns a background task that calls
                receive() to listen for client disconnect. If that call
                returns immediately with anything other than
                http.disconnect, Django raises AssertionError. Blocking
                here lets the response complete normally; Django cancels
                this task once the response is sent.
                """
                nonlocal got_body
                if not got_body:
                    got_body = True
                    return body_msg
                # Block until Django cancels this task after the response
                # is sent. This prevents the disconnect listener from
                # interfering with response processing.
                await asyncio.Future()

            await wrapped(scope, django_receive, send)

    return combined
