#!/usr/bin/env python3
"""content/posts/*.md の frontmatter を読み取り、site/data/manifest.json を生成する。

GitHub Actions のビルドステップから呼び出される想定。
依存ライブラリは PyYAML のみ。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "content" / "posts"
OUTPUT_PATH = ROOT / "site" / "data" / "manifest.json"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
REQUIRED_FIELDS = ["title", "date", "source_name", "source_url", "summary"]


def parse_post(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"frontmatter (--- で囲まれたメタ情報) が見つかりません: {path.name}")

    front_raw, body = match.groups()
    meta = yaml.safe_load(front_raw) or {}

    missing = [key for key in REQUIRED_FIELDS if key not in meta or meta[key] in (None, "")]
    if missing:
        raise ValueError(f"{path.name}: 必須フィールドが不足しています -> {missing}")

    return {
        "id": path.stem,
        "title": str(meta["title"]),
        "date": str(meta["date"]),
        "source_name": str(meta["source_name"]),
        "source_url": str(meta["source_url"]),
        "tags": list(meta.get("tags") or []),
        "summary": str(meta["summary"]),
        "body": body.strip(),
    }


def main() -> None:
    if not POSTS_DIR.exists():
        print(f"投稿ディレクトリが見つかりません: {POSTS_DIR}", file=sys.stderr)
        sys.exit(1)

    posts: list[dict] = []
    errors: list[str] = []

    for path in sorted(POSTS_DIR.glob("*.md")):
        try:
            posts.append(parse_post(path))
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    if errors:
        for err in errors:
            print(f"::error::{err}", file=sys.stderr)
        sys.exit(1)

    # 新しい日付が先頭に来るように並び替え
    posts.sort(key=lambda p: p["date"], reverse=True)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "posts": posts,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"{len(posts)}件の記事から manifest.json を生成しました -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
