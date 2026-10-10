from __future__ import annotations

import base64

from pipeline import cards, config


def test_uploaded_logo_overrides_configured_default(tmp_path, monkeypatch):
    uploaded = tmp_path / "uploaded.png"
    uploaded_bytes = b"uploaded-logo-bytes"
    uploaded.write_bytes(uploaded_bytes)
    default = tmp_path / "default.png"
    default.write_bytes(b"default-logo-bytes")
    monkeypatch.setattr(config, "LOGO_PNG", default)

    expected = "data:image/png;base64," + base64.b64encode(uploaded_bytes).decode()
    assert cards._logo_data_uri(uploaded) == expected


def test_outro_template_renders_follow_for_more_cta():
    brand = config.BRAND
    html = cards._env.get_template("outro_card.html").render(
        w=config.WIDTH,
        h=config.HEIGHT,
        display_font=brand["display_font"],
        body_font=brand["body_font"],
        accent=brand["accent"],
        accent_2=brand["accent_2"],
        text=brand["text"],
        muted=brand["muted"],
        name="ReelGen",
        url="https://example.com",
        tagline="",
        logo_data="",
        cta="Follow for more",
    )

    assert '<div class="btn">Follow for more</div>' in html
    assert '<div class="btn">https://example.com</div>' not in html
