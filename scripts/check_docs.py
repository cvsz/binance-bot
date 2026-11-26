#!/usr/bin/env python3
"""Check that relative links in Markdown files point to existing files and anchors.

Anchors are resolved against explicit `<a id="...">` tags and ASCII heading slugs
(GitHub style). Exit 1 if anything is broken.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
ANCHOR_TAG_RE = re.compile(r'<a\s+id="([^"]+)"')
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
SKIP_DIRS = {".venv", "venv", ".git", "node_modules", ".pytest_cache", ".ruff_cache"}


def slug(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def anchors(md: Path) -> set[str]:
    text = FENCE_RE.sub("", md.read_text(encoding="utf-8"))
    anchors = set(ANCHOR_TAG_RE.findall(text))
    seen: dict[str, int] = {}
    for heading in HEADING_RE.findall(text):
        base = slug(heading)
        n = seen.get(base, 0)
        seen[base] = n + 1
        anchors.add(base if n == 0 else f"{base}-{n}")  # GitHub: second "Foo" becomes "foo-1"
    return anchors


def main(root: Path) -> int:
    files = [p for p in root.rglob("*.md") if not SKIP_DIRS.intersection(p.relative_to(root).parts)]
    errors = []
    for md in sorted(files):
        text = FENCE_RE.sub("", md.read_text(encoding="utf-8"))
        for target in LINK_RE.findall(text):
            if re.match(r"^[a-z]+:", target):  # http:, https:, mailto:
                continue
            path_part, _, frag = target.partition("#")
            dest = (md.parent / path_part).resolve() if path_part else md
            rel = md.relative_to(root)
            if not dest.exists():
                errors.append(f"{rel}: missing file -> {target}")
            elif frag and dest.suffix == ".md" and frag not in anchors(dest):
                errors.append(f"{rel}: missing anchor -> {target}")
    for e in errors:
        print("BROKEN", e)
    print(f"docs-check: {len(files)} files, {len(errors)} broken link(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))
