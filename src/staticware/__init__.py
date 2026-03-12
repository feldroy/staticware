"""Top-level package for Staticware."""

from staticware.middleware import HashedStatic, StaticRewriteMiddleware

__all__ = ["HashedStatic", "StaticRewriteMiddleware"]
