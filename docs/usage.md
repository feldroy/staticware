# Usage

## Basic Setup

Create a `HashedStatic` instance pointing at your static files directory, then wrap your ASGI app with `StaticRewriteMiddleware`:

```python
from staticware import HashedStatic, StaticRewriteMiddleware

static = HashedStatic("static")

# Mount it however your framework mounts sub-apps:
app.mount("/static", static)

# Wrap the app to rewrite static paths in HTML responses:
app = StaticRewriteMiddleware(app, static=static)
```

`HashedStatic` hashes every file in the directory at startup. When a browser requests the hashed filename, it gets an immutable cache header. When it requests the original filename, the file is served without aggressive caching.

File hashes are computed once when `HashedStatic` is created. If you deploy updated static files, restart the ASGI process to pick up the new hashes. This is the same model used by Starlette and most ASGI static file handlers.

## Resolving URLs in Templates

Use `static.url()` to get the cache-busted URL for a file:

```python
static.url("styles.css")       # /static/styles.a1b2c3d4.css
static.url("images/logo.png")  # /static/images/logo.7e4f9a01.png
```

Unknown paths are returned unchanged with the prefix:

```python
static.url("nonexistent.js")   # /static/nonexistent.js
```

## Automatic HTML Rewriting

`StaticRewriteMiddleware` rewrites static paths in HTML responses automatically. Any `text/html` response that references `/static/styles.css` will have it replaced with the hashed equivalent. Non-HTML responses pass through untouched.

This means cache busting works even without explicit `static.url()` calls in templates.

## Configuration

### Custom Prefix

```python
static = HashedStatic("static", prefix="/assets")
static.url("styles.css")  # /assets/styles.a1b2c3d4.css
```

### Hash Length

The default hash is 8 characters from the SHA-256 digest. To change it:

```python
static = HashedStatic("static", hash_length=12)
```
