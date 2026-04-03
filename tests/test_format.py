"""Tests for platform-specific message formatters."""

from echo.shared.format import to_slack, to_discord, to_telegram, to_whatsapp, to_plain


class TestSlackFormatter:
    def test_bold(self):
        assert to_slack("**hello**") == "*hello*"

    def test_link(self):
        assert to_slack("[click](https://example.com)") == "<https://example.com|click>"

    def test_header_to_bold(self):
        assert to_slack("## Section Title") == "*Section Title*"

    def test_inline_code_preserved(self):
        assert to_slack("run `npm install`") == "run `npm install`"

    def test_code_block_preserved(self):
        md = "```python\nprint('hi')\n```"
        result = to_slack(md)
        assert "```python\nprint('hi')\n```" in result

    def test_bold_inside_code_not_converted(self):
        md = "`**not bold**`"
        result = to_slack(md)
        assert "**not bold**" in result

    def test_combined(self):
        md = "## Title\n\n**Bold** and [link](https://x.com)\n\n```\ncode\n```"
        result = to_slack(md)
        assert "*Title*" in result
        assert "*Bold*" in result
        assert "<https://x.com|link>" in result
        assert "```\ncode\n```" in result


class TestDiscordFormatter:
    def test_passthrough(self):
        md = "**bold** *italic* `code` [link](url)"
        assert to_discord(md) == md

    def test_image_to_url(self):
        assert to_discord("![alt](https://img.png)") == "https://img.png"


class TestTelegramFormatter:
    def test_bold(self):
        assert "<b>hello</b>" in to_telegram("**hello**")

    def test_inline_code(self):
        assert "<code>foo</code>" in to_telegram("`foo`")

    def test_code_block(self):
        result = to_telegram("```\ncode\n```")
        assert "<pre>" in result
        assert "code" in result

    def test_link(self):
        result = to_telegram("[click](https://example.com)")
        assert '<a href="https://example.com">click</a>' in result

    def test_header_to_bold(self):
        result = to_telegram("## Section")
        assert "<b>Section</b>" in result

    def test_bare_angle_brackets_escaped(self):
        result = to_telegram("use x < 5 and y > 3")
        assert "&lt;" in result
        assert "&gt;" in result

    def test_allowed_tags_not_escaped(self):
        result = to_telegram("**bold**")
        assert "<b>" in result
        assert "&lt;b&gt;" not in result


class TestWhatsAppFormatter:
    def test_bold(self):
        assert to_whatsapp("**hello**") == "*hello*"

    def test_link_degrades(self):
        assert to_whatsapp("[click](https://x.com)") == "click (https://x.com)"

    def test_header_to_bold(self):
        assert to_whatsapp("## Title") == "*Title*"


class TestPlainFormatter:
    def test_strips_bold(self):
        assert to_plain("**hello**") == "hello"

    def test_strips_italic(self):
        assert to_plain("*hello*") == "hello"

    def test_strips_code_fences(self):
        assert "print" in to_plain("```\nprint('hi')\n```")
        assert "```" not in to_plain("```\nprint('hi')\n```")

    def test_link_preserves_url(self):
        assert to_plain("[click](https://x.com)") == "click (https://x.com)"

    def test_strips_headers(self):
        assert to_plain("## Title") == "Title"

    def test_strips_images(self):
        assert to_plain("![photo](https://img.png)") == "photo"
