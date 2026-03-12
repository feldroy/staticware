from pathlib import Path

import pytest

from staticware import StaticFiles


@pytest.fixture()
def static_dir(tmp_path: Path) -> Path:
    d = tmp_path / "static"
    d.mkdir()
    (d / "styles.css").write_text("body { color: red; }")
    sub = d / "images"
    sub.mkdir()
    (sub / "logo.png").write_bytes(b"\x89PNG fake image data")
    return d


@pytest.fixture()
def static(static_dir: Path) -> StaticFiles:
    return StaticFiles(static_dir)
