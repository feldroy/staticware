# Contributing

Staticware is about 270 lines of production code. You can read the entire middleware in one sitting, and that's intentional. Contributions that keep the project small and focused are the ones that land.

## Understanding the Project

Before contributing, read `src/staticware/middleware.py`. The whole thing. It's two classes, a couple of helpers, and zero runtime dependencies. The zero-dependency constraint is a design choice: every ASGI framework already has enough dependencies. Staticware should not add to the pile.

The test suite at `tests/test_staticware.py` talks directly to the ASGI protocol. Tests construct scope dicts, call the middleware, and collect `send()` messages. No framework test client, no HTTP library. If you're adding a feature, your test should work at the same level.

## What We're Looking For

Bug reports, test cases, docs improvements, and features that fit the project's scope. File issues and pull requests at https://github.com/feldroy/staticware/issues.

If you're proposing a feature, open an issue first. Describe what it does and why it belongs in a static file middleware. Not everything does, and that's fine.

## AI Contributions

AI-assisted contributions are welcome. AI-generated slop is not.

If you use an AI tool to write code for this project, you are responsible for every line it produces. Review it the way you'd review a junior developer's pull request: check the logic, verify the tests actually test what they claim, and make sure the commit messages explain the why, not just the what.

Specific expectations:

- **Tight.** No boilerplate, no placeholder comments, no "Replace this with..." stubs. If the AI generated scaffolding, strip it before submitting.
- **Atomic.** One logical change per commit. If your PR touches the middleware and the docs and the CI config, those should be separate commits with separate messages.
- **Tested.** Red/green TDD: write a failing test, then write the code that makes it pass. If you can't write the failing test first, you probably don't understand the change well enough yet.

## Development Setup

```sh
git clone git@github.com:your_name_here/staticware.git
cd staticware/
uv sync
```

Run the full quality suite (format, lint, type check, test):

```sh
just qa
```

Run tests alone:

```sh
just test
```

Preview docs locally:

```sh
just docs-serve
```

## Pull Request Guidelines

1. Include tests. The coverage threshold is 90% and the project currently sits at 98%.
2. If you add functionality, update the docs and the README features list.
3. Tests must pass on Python 3.12, 3.13, and 3.14. CI runs automatically on every PR.

## Releasing

1. Bump the version:
   ```bash
   uv version <version>        # or: uv version --bump minor
   ```
   Then write `CHANGELOG/<version>.md`.
2. Commit:
   ```bash
   git add pyproject.toml uv.lock CHANGELOG/
   git commit -m "Release <version>"
   ```
3. Tag and push:
   ```bash
   just tag
   ```
4. Wait for the publish workflow to build, attest, and publish to PyPI.
5. Create the GitHub Release:
   ```bash
   gh release create v<version> --verify-tag \
     --title "Staticware <version>" \
     --notes-file CHANGELOG/<version>.md
   ```

## Code of Conduct

This project follows the [Contributor Code of Conduct](CODE_OF_CONDUCT.md).
