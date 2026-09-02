#!/usr/bin/env python3
"""OpenAI Responses API (web_search) でAI関連ニュースを収集・要約し、
content/posts/ 配下にMarkdown記事として書き出すスクリプト。

GitHub Actions (.github/workflows/news_bot.yml) から定期実行される想定。
生成したファイルをコミット・pushするのはワークフロー側の役目で、
このスクリプトはローカルにファイルを書き出すところまでを担当する。

使い方:
    OPENAI_API_KEY=sk-... python scripts/generate_news.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "content" / "posts"

MODEL = os.environ.get("NEWS_BOT_MODEL", "gpt-5-mini")
ARTICLE_COUNT = os.environ.get("NEWS_BOT_COUNT", "5〜10")
LOOKBACK_DAYS = 14

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
REQUIRED_FIELDS = ["title", "date", "source_name", "source_url", "summary"]
SLUG_RE = re.compile(r"^[a-z0-9\-]+$")
PREFERRED_TAGS = ["Agent", "OSS", "Framework", "Benchmark", "Research", "Safety", "Policy"]
BANNED_TAGS = {"test", "サンプル", "sample"}

PROMPT_TEMPLATE = """直近1〜3日以内の、主要なAI関連ニュースを{count}件選んでください。
それぞれについて、以下のJSONスキーマの配列を出力してください。
説明や前置きは不要です。```json の中に配列だけを出力してください。

[
  {{
    "title": "記事タイトル(日本語、40字以内目安)",
    "date": "YYYY-MM-DD",
    "source_name": "情報源の名前(例: OpenAI Blog, TechCrunch, Reuters)",
    "source_url": "https://情報源への直接リンク",
    "slug": "英単語をハイフンで繋いだ短いslug(小文字英数字とハイフンのみ、例: eu-google-ai-competition)",
    "tags": ["タグ1", "タグ2"],
    "summary": "2〜3文程度の要約。何が起きたか、なぜ重要かを簡潔に。",
    "body": "任意の補足コメントや背景説明(省略可、空文字でも良い)"
  }}
]

条件:
- 一次情報(公式ブログ、プレスリリース、大手報道)を優先し、真偽不明の噂は扱わない
- tagsは {tags} を優先して使う。当てはまらない場合のみ新しいタグを追加してよい
- "Test" や "サンプル" など、動作確認用・仮のタグやタイトルは使わないこと
- source_url は実在する具体的なURLにすること(架空のURLを作らない)
- 以下は直近{lookback}日間に既に投稿済みのニュースなので、同じ話題は選ばないこと:
{existing}
"""


def load_existing_source_urls() -> list[str]:
    if not POSTS_DIR.exists():
        return []
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)
    urls: list[str] = []
    for path in sorted(POSTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = FRONTMATTER_RE.match(text)
        if not match:
            continue
        meta = yaml.safe_load(match.group(1)) or {}
        date_str = str(meta.get("date", ""))
        try:
            post_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            post_date = None
        if post_date is None or post_date >= cutoff:
            title = meta.get("title", "")
            url = meta.get("source_url", "")
            if url:
                urls.append(url)
            if title or url:
                urls.append(f"- {title} ({url})")
    return urls


def build_prompt() -> str:
    existing = load_existing_source_urls()
    existing_text = "\n".join(u for u in existing if u.startswith("-")) or "(なし)"
    return PROMPT_TEMPLATE.format(
        count=ARTICLE_COUNT,
        tags=", ".join(PREFERRED_TAGS),
        lookback=LOOKBACK_DAYS,
        existing=existing_text,
    )


def extract_json_array(text: str) -> list[dict]:
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    raw = fenced.group(1) if fenced else text[text.find("["): text.rfind("]") + 1]
    return json.loads(raw)


def slugify_fallback(item: dict, index: int) -> str:
    url_path = urlparse(item.get("source_url", "")).path.strip("/").split("/")[-1]
    candidate = re.sub(r"[^a-z0-9\-]+", "-", url_path.lower()).strip("-")
    if candidate:
        return candidate[:60]
    return f"article-{index}"


def normalize_item(item: dict, index: int, seen_urls: set[str]) -> dict | None:
    missing = [k for k in REQUIRED_FIELDS if not item.get(k)]
    if missing:
        print(f"::warning:: {index}件目: 必須フィールド不足 {missing} のためスキップ", file=sys.stderr)
        return None

    source_url = str(item["source_url"]).strip()
    if source_url in seen_urls:
        print(f"::warning:: {index}件目: source_urlが重複のためスキップ ({source_url})", file=sys.stderr)
        return None

    date_str = str(item["date"]).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    slug = str(item.get("slug", "")).strip().lower()
    if not SLUG_RE.match(slug):
        slug = slugify_fallback(item, index)

    tags = [t for t in (item.get("tags") or []) if str(t).strip().lower() not in BANNED_TAGS]

    seen_urls.add(source_url)
    return {
        "title": str(item["title"]).strip(),
        "date": date_str,
        "source_name": str(item["source_name"]).strip(),
        "source_url": source_url,
        "slug": slug,
        "tags": tags,
        "summary": str(item["summary"]).strip(),
        "body": str(item.get("body") or "").strip(),
    }


def write_post(item: dict) -> Path:
    filename = f"{item['date']}-{item['slug']}.md"
    path = POSTS_DIR / filename
    n = 2
    while path.exists():
        path = POSTS_DIR / f"{item['date']}-{item['slug']}-{n}.md"
        n += 1

    frontmatter = {
        "title": item["title"],
        "date": item["date"],
        "source_name": item["source_name"],
        "source_url": item["source_url"],
        "tags": item["tags"],
        "summary": item["summary"],
    }
    front_yaml = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    body = item["body"] + "\n" if item["body"] else ""
    path.write_text(f"---\n{front_yaml}\n---\n\n{body}", encoding="utf-8")
    return path


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("エラー: OPENAI_API_KEY が設定されていません。", file=sys.stderr)
        sys.exit(1)

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    client = OpenAI(api_key=api_key)

    resp = client.responses.create(
        model=MODEL,
        input=build_prompt(),
        tools=[{"type": "web_search"}],
        max_output_tokens=8000,
    )
    output_text = (resp.output_text or "").strip()
    if not output_text:
        print("エラー: AIから空の応答でした。", file=sys.stderr)
        sys.exit(1)

    try:
        raw_items = extract_json_array(output_text)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"エラー: JSON解析に失敗しました: {exc}", file=sys.stderr)
        print(output_text, file=sys.stderr)
        sys.exit(1)

    existing_urls = {
        yaml.safe_load(FRONTMATTER_RE.match(p.read_text(encoding="utf-8")).group(1)).get("source_url")
        for p in POSTS_DIR.glob("*.md")
        if FRONTMATTER_RE.match(p.read_text(encoding="utf-8"))
    }

    written: list[Path] = []
    for i, raw_item in enumerate(raw_items, start=1):
        item = normalize_item(raw_item, i, existing_urls)
        if item is None:
            continue
        path = write_post(item)
        written.append(path)
        print(f"作成: {path.relative_to(ROOT)} ({item['title']})")

    print(f"\n合計 {len(written)} 件の記事を書き出しました。")


if __name__ == "__main__":
    main()
