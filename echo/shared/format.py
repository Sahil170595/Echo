"""Platform-specific message formatters.

JARVIS returns standard Markdown. Each platform has its own formatting language:
- Slack: mrkdwn (different bold/italic/link syntax)
- Discord: mostly standard Markdown (minor differences)
- Telegram: HTML subset (official recommendation over MarkdownV2)
- WhatsApp: limited formatting (*bold*, _italic_, ~strike~, ```code```)
- Email: plain text (strip all formatting)

These converters are intentionally simple — they handle the common cases
(bold, italic, code, links, headers) without trying to be a full Markdown parser.
Edge cases degrade to readable plain text, which is fine.
"""

from __future__ import annotations

import re


def to_slack(md: str) -> str:
    """Convert Markdown to Slack mrkdwn.

    Key differences from standard Markdown:
    - Bold: *text* (not **text**)
    - Italic: _text_ (same)
    - Links: <url|text> (not [text](url))
    - Code blocks: ```code``` (same)
    - No headers — convert to bold
    """
    text = md

    # Code blocks first (protect from other transforms)
    blocks: list[str] = []

    def _protect_code_block(m: re.Match) -> str:
        blocks.append(m.group(0))
        return f"\x00CODEBLOCK{len(blocks) - 1}\x00"

    text = re.sub(r"```[\s\S]*?```", _protect_code_block, text)

    # Inline code — protect
    inlines: list[str] = []

    def _protect_inline(m: re.Match) -> str:
        inlines.append(m.group(0))
        return f"\x00INLINE{len(inlines) - 1}\x00"

    text = re.sub(r"`[^`]+`", _protect_inline, text)

    # Links: [text](url) → <url|text>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)

    # Bold: **text** → *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    # Headers: ## text → *text*
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    # Restore protected code
    for i, block in enumerate(blocks):
        text = text.replace(f"\x00CODEBLOCK{i}\x00", block)
    for i, inline in enumerate(inlines):
        text = text.replace(f"\x00INLINE{i}\x00", inline)

    return text


def to_discord(md: str) -> str:
    """Convert Markdown to Discord format.

    Discord supports standard Markdown almost entirely.
    Only strip things Discord doesn't support.
    """
    # Discord handles standard markdown well. Just pass through.
    # Only fix: image syntax ![alt](url) → url (Discord embeds auto-preview)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\2", md)
    return text


def to_telegram(md: str) -> str:
    """Convert Markdown to Telegram HTML.

    Telegram supports a limited HTML subset:
    <b>bold</b>, <i>italic</i>, <code>code</code>,
    <pre>code block</pre>, <a href="url">text</a>

    HTML is more reliable than MarkdownV2 (fewer escaping issues).
    """
    text = md

    # Code blocks: ```lang\ncode``` → <pre>code</pre>
    text = re.sub(
        r"```(?:\w*\n)?([\s\S]*?)```",
        r"<pre>\1</pre>",
        text,
    )

    # Inline code: `code` → <code>code</code>
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # Bold: **text** → <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Italic: *text* or _text_ → <i>text</i>
    # Only match *text* that isn't already inside <b> tags
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)

    # Links: [text](url) → <a href="url">text</a>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Headers: ## text → <b>text</b>
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Escape remaining HTML-special chars in non-tag contexts
    # (Telegram rejects unmatched < or >)
    # Only escape < > that aren't part of our tags
    text = _escape_bare_html(text)

    return text


def _escape_bare_html(text: str) -> str:
    """Escape < and > that aren't part of allowed Telegram HTML tags."""
    allowed = {"b", "i", "code", "pre", "a", "/b", "/i", "/code", "/pre", "/a"}
    result = []
    i = 0
    while i < len(text):
        if text[i] == "<":
            # Check if this is an allowed tag
            end = text.find(">", i)
            if end != -1:
                tag_content = text[i + 1:end].split()[0].split('"')[0]
                if tag_content in allowed or tag_content.startswith("a "):
                    result.append(text[i:end + 1])
                    i = end + 1
                    continue
            result.append("&lt;")
            i += 1
        elif text[i] == ">":
            result.append("&gt;")
            i += 1
        elif text[i] == "&" and not text[i:].startswith("&lt;") and not text[i:].startswith("&gt;"):
            result.append("&amp;")
            i += 1
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def to_whatsapp(md: str) -> str:
    """Convert Markdown to WhatsApp formatting.

    WhatsApp supports:
    *bold*, _italic_, ~strikethrough~, ```code block```, `inline code`
    No links, no headers — degrade gracefully.
    """
    text = md

    # Code blocks — already use ``` syntax, pass through
    # Inline code — already uses ` syntax, pass through

    # Bold: **text** → *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    # Links: [text](url) → text (url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)

    # Headers: ## text → *text*
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    return text


def to_plain(md: str) -> str:
    """Strip all Markdown formatting to plain text. Used for email."""
    text = md

    # Code blocks: remove fences
    text = re.sub(r"```(?:\w*\n)?([\s\S]*?)```", r"\1", text)

    # Inline code: remove backticks
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Bold/italic: remove markers
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)

    # Images: ![alt](url) → alt (must come before links)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)

    # Links: [text](url) → text (url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)

    # Headers: remove # prefix
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    return text
