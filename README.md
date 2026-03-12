# Staticware

![PyPI version](https://img.shields.io/pypi/v/staticware.svg)

Staticware is ASGI middleware that rewrites static file paths to c

* Created by **[Audrey M. Roy Greenfeld](https://audrey.feldroy.com)**
  * GitHub: https://github.com/audreyfeldroy
  * PyPI: https://pypi.org/user/audreyr/
* PyPI package: https://pypi.org/project/staticware/
* Free software: MIT License

## Features

* TODO

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
# Clone your fork
git clone git@github.com:your_username/staticware.git
cd staticware

# Install in editable mode with live updates
uv tool install --editable .
```

This installs the CLI globally but with live updates - any changes you make to the source code are immediately available when you run `staticware`.

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
