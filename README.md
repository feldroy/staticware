# Staticware

![PyPI version](https://img.shields.io/pypi/v/staticware.svg)

ASGI middleware for static file serving with content-based cache busting. Zero runtime dependencies.

* Created by **[Audrey M. Roy Greenfeld](https://audrey.feldroy.com)**
  * GitHub: https://github.com/audreyfeldroy
  * PyPI: https://pypi.org/user/audreyr/
* PyPI package: https://pypi.org/project/staticware/
* Free software: MIT License

## Features

* Serves static files over ASGI with content-hashed filenames for cache busting
* Hashed filenames get `Cache-Control: public, max-age=31536000, immutable`
* Original filenames still work, without aggressive caching
* `StaticRewriteMiddleware` automatically rewrites static paths in HTML responses
* `static.url()` resolves cache-busted URLs for use in templates
* Works with any ASGI framework: Starlette, FastAPI, Air, Litestar, Django, or raw ASGI
* Zero runtime dependencies

## Quick Start

```python
from staticware import HashedStatic, StaticRewriteMiddleware

# Point at your static files directory
static = HashedStatic("static")

# Mount it however your framework mounts sub-apps:
app.mount("/static", static)

# Wrap any ASGI app to rewrite static paths in HTML responses
StaticRewriteMiddleware(app, static=static)

# In templates, resolve cache-busted URLs:
static.url("styles.css")       # /static/styles.a1b2c3d4.css
static.url("images/logo.png")  # /static/images/logo.7e4f9a01.png
```

## Documentation

Documentation is built with [Zensical](https://zensical.org/) and deployed to GitHub Pages.

* **Live site:** https://feldroy.github.io/staticware/
* **Preview locally:** `just docs-serve` (serves at http://localhost:8000)
* **Build:** `just docs-build`

API documentation is auto-generated from docstrings using [mkdocstrings](https://mkdocstrings.github.io/).

Docs deploy automatically on push to `main` via GitHub Actions. To enable this, go to your repo's Settings > Pages and set the source to **GitHub Actions**.

## Development

To set up for local development:

```bash
git clone git@github.com:feldroy/staticware.git
cd staticware
uv sync
```

Run tests:

```bash
uv run pytest
```

Run quality checks (format, lint, type check, test):

```bash
just qa
```

## Author

Staticware was created in 2026 by Audrey M. Roy Greenfeld.

Built with [Cookiecutter](https://github.com/cookiecutter/cookiecutter) and the [audreyfeldroy/cookiecutter-pypackage](https://github.com/audreyfeldroy/cookiecutter-pypackage) project template.
