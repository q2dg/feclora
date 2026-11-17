#!/usr/bin/env python3
"""Validate local links and guide-card assets in the Jekyll documentation tree.

This deliberately checks local source paths only. External URLs are not probed,
so a transient provider outage cannot make the documentation build flaky.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MARKDOWN_LINK = re.compile(r"!?(?:\[[^\]]*\])\(([^)\s]+)(?:\s+[^)]*)?\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
HTML_ATTR = re.compile(r"\b(?:href|src)\s*=\s*(['\"])(.*?)\1", re.IGNORECASE)
LIQUID_PATH = re.compile(r"""\{\{\s*['\"]([^'\"]+)['\"]""")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,}).*$", re.MULTILINE)


def without_code(text: str) -> str:
    lines = text.splitlines()
    result: list[str] = []
    fence_char = None
    fence_size = 0
    for line in lines:
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            token = match.group(1)
            if fence_char is None:
                fence_char, fence_size = token[0], len(token)
            elif token[0] == fence_char and len(token) >= fence_size:
                fence_char, fence_size = None, 0
            continue
        if fence_char is None:
            result.append(line)
    return "\n".join(result)


def source_candidate(source: Path, raw: str) -> Path | None:
    raw = raw.strip().strip("<>")
    liquid = LIQUID_PATH.search(raw)
    if liquid:
        raw = liquid.group(1)
    if not raw or "{{" in raw or raw.startswith(("#", "http:", "https:", "mailto:", "tel:", "data:", "javascript:")):
        return None
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        return None
    target = unquote(parsed.path)
    if not target:
        return None
    if target.startswith("/"):
        candidate = DOCS / target.lstrip("/")
    else:
        candidate = source.parent / target
    candidate = candidate.resolve()
    try:
        candidate.relative_to(DOCS.resolve())
    except ValueError:
        return None
    if candidate.suffix.lower() == ".html":
        markdown = candidate.with_suffix(".md")
        if markdown.is_file():
            candidate = markdown
    if candidate.is_dir():
        candidate = candidate / "index.md"
    return candidate


def main() -> int:
    errors: list[str] = []
    markdown_files = sorted(DOCS.rglob("*.md"))
    checked_links = 0
    for source in markdown_files:
        text = without_code(source.read_text(encoding="utf-8"))
        targets = [m.group(1) for m in MARKDOWN_LINK.finditer(text)]
        targets += [m.group(1) for m in REFERENCE_LINK.finditer(text)]
        targets += [m.group(2) for m in HTML_ATTR.finditer(text)]
        for raw in targets:
            candidate = source_candidate(source, raw)
            if candidate is None:
                continue
            checked_links += 1
            if not candidate.is_file():
                relative = source.relative_to(ROOT)
                errors.append(f"{relative}: broken local link/asset: {raw}")

    guide_index = DOCS / "GUIDES.md"
    if guide_index.is_file():
        guide_text = guide_index.read_text(encoding="utf-8")
        cards = re.findall(r'<article\s+class="guide-card">(.*?)</article>', guide_text, re.DOTALL)
        for number, card in enumerate(cards, start=1):
            image_match = re.search(r'<img\b[^>]*\bsrc="([^"]+)"', card, re.IGNORECASE)
            alt_match = re.search(r'<img\b[^>]*\balt="([^"]+)"', card, re.IGNORECASE)
            link_match = re.search(r'<a\b[^>]*\bhref="([^"]+)"', card, re.IGNORECASE)
            if not image_match:
                errors.append(f"docs/GUIDES.md: guide card {number} has no illustration")
            if not alt_match or not alt_match.group(1).strip():
                errors.append(f"docs/GUIDES.md: guide card {number} has no descriptive image alt text")
            if not link_match:
                errors.append(f"docs/GUIDES.md: guide card {number} has no destination link")
        if not cards:
            errors.append("docs/GUIDES.md: no guide cards found")

    if errors:
        print("Documentation validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"Documentation validation passed: {len(markdown_files)} Markdown files, "
          f"{checked_links} local links/assets, and {len(cards) if guide_index.is_file() else 0} illustrated guide cards.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
