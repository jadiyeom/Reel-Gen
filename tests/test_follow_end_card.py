from __future__ import annotations

import base64

import pytest

from pipeline import cards, config
from pipeline.end_card import resolve_outro_image


def test_uploaded_logo_overrides_configured_default(tmp_path, monkeypatch):
    uploaded = tmp_path / "uploaded.png"
    uploaded_bytes = b"uploaded-logo-bytes"
    uploaded.write_bytes(uploaded_bytes)
    default = tmp_path / "default.png"
    default.write_bytes(b"default-logo-bytes")
    monkeypatch.setattr(config, "LOGO_PNG", default)

    expected = "data:image/png;base64," + base64.b64encode(uploaded_bytes).decode()
    assert cards._logo_data_uri(uploaded) == expected


def test_default_backspace_art_is_used_when_no_custom_outro(tmp_path, monkeypatch):
    default = tmp_path / "backspace_outro.webp"
    default.write_bytes(b"default-outro")
    monkeypatch.setattr(config, "DEFAULT_OUTRO_IMAGE", default)

    assert resolve_outro_image() == default


def test_custom_outro_image_overrides_default(tmp_path, monkeypatch):
    default = tmp_path / "backspace_outro.webp"
    default.write_bytes(b"default-outro")
    custom = tmp_path / "my-outro.png"
    custom.write_bytes(b"custom-outro")
    monkeypatch.setattr(config, "DEFAULT_OUTRO_IMAGE", default)

    assert resolve_outro_image(custom) == custom.resolve()


def test_missing_default_outro_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_OUTRO_IMAGE", tmp_path / "missing.webp")
    with pytest.raises(FileNotFoundError, match="Default|Restore|outro image"):
        resolve_outro_image()
