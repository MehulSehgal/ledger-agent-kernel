from html.parser import HTMLParser
from pathlib import Path
import re


ROOT = Path(__file__).parent
STATIC = ROOT / "static"


class ButtonNameParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.buttons = []
        self._active = None

    def handle_starttag(self, tag, attrs):
        if tag == "button":
            self._active = {"attrs": dict(attrs), "text": []}
        elif self._active is not None:
            return

    def handle_data(self, data):
        if self._active is not None:
            self._active["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "button" and self._active is not None:
            self.buttons.append(self._active)
            self._active = None


def _tokens(block):
    return {
        name: value.lower()
        for name, value in re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block)
    }


def _luminance(color):
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def _contrast(foreground, background):
    light, dark = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_theme_text_tokens_meet_wcag_aa_contrast():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    dark_block = re.search(r":root\s*\{([^}]+)}", css).group(1)
    light_block = re.search(r'\[data-theme="light"]\s*\{([^}]+)}', css).group(1)
    for theme in (_tokens(dark_block), _tokens(light_block)):
        for foreground in ("text", "muted", "accent", "ok", "warn", "danger"):
            for background in ("bg", "surface", "surface-2"):
                assert _contrast(theme[foreground], theme[background]) >= 4.5, (
                    foreground,
                    background,
                    theme,
                )
    assert "button-on-accent" in _tokens(dark_block)
    assert "button-on-danger" in _tokens(dark_block)


def test_accessibility_controls_focus_targets_live_regions_and_motion():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    parser = ButtonNameParser()
    parser.feed(html)
    for button in parser.buttons:
        accessible_name = button["attrs"].get("aria-label") or "".join(button["text"]).strip()
        assert accessible_name, button["attrs"]

    assert ":focus-visible" in css
    assert re.search(r":focus-visible\s*\{[^}]*outline:\s*(?!none)", css)
    assert "44px" in css
    assert 'aria-live="polite"' in html
    assert 'aria-live="assertive"' in html or 'role="alert"' in html
    assert "prefers-reduced-motion: reduce" in css
    assert not re.search(r"tabindex=[\"']([1-9]\d*)", html, re.IGNORECASE)
    assert not re.search(r"tabIndex\s*=\s*[1-9]\d*", script)


def test_page_metadata_route_titles_and_favicon():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert re.search(r'<meta name="description" content="[^"]+">', html)
    assert 'rel="icon"' in html
    assert (STATIC / "favicon.svg").is_file()
    assert "routeTitles" in script
    for title in ("Ledger — Home", "Ledger — Workspace", "Ledger — Safety", "Ledger — Evaluation"):
        assert title in script


def test_brief_print_rules_hide_shell_and_fit_a_clean_page():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "@page" in css
    assert "#workspace-screen" in css
    assert ".brief-result" in css
    assert ".evidence-panel" in css
    assert "break-inside: avoid" in css
    assert "print-brief" in css
