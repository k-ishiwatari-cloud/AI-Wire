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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import yaml
from openai import OpenAI

from news_validation import (
    UrlCheck,
    check_url,
    extract_source_urls,
    find_similar_title,
    is_cited,
    normalize_url,
)

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "content" / "posts"

MODEL = os.environ.get("NEWS_BOT_MODEL", "gpt-5-mini")
ARTICLE_COUNT = os.environ.get("NEWS_BOT_COUNT", "5〜10")
LOOKBACK_DAYS = 14

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
REQUIRED_FIELDS = ["title", "date", "source_name", "source_url", "summary"]
SLUG_RE = re.compile(r"^[a-z0-9\-]+$")
PREFERRED_TAGS = ["Release", "Agent", "OSS", "Framework", "Benchmark", "Research", "Safety", "Policy", "Japan"]
BANNED_TAGS = {"test", "サンプル", "sample"}

PROMPT_TEMPLATE = """直近0〜2日以内の、主要なAI関連ニュースを{count}件選んでください。
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
- 日本に関係する重要なAIニュースも収集対象にする。日本企業、日本の政府機関による
  AIの製品・モデル・導入・政策・安全性に関する発表を優先して探す。経済産業省、総務省、デジタル庁、
  企業・政府機関の公式発表を優先し、補助的に信頼できる日本語の大手報道を用いること。
- 該当期間に掲載価値のある日本関連ニュースがある場合は、全体の中に少なくとも1件含める。
  日本関連の記事には必ず "Japan" タグを付ける。日本の話題でない記事にこのタグを付けない。
- tagsは {tags}, Other を優先して使う。新しいAIサービス・製品・モデルのリリース発表は
  "Release" を使う。上記のどれにも当てはまらない場合のみ "Other" を使う
  (それでも当てはまらない場合に限り、新しいタグを追加してもよい)
- "Test" や "サンプル" など、動作確認用・仮のタグやタイトルは使わないこと
- source_url は実在する具体的なURLにすること(架空のURLを作らない)
- 以下は直近{lookback}日間に既に投稿済みのニュースなので、同じ話題は選ばないこと:
{existing}
"""


def load_recent_posts_meta() -> list[dict]:
    """直近 LOOKBACK_DAYS 日間(日付不明を含む)の既存記事の frontmatter。"""
    if not POSTS_DIR.exists():
        return []
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)
    metas: list[dict] = []
    for path in sorted(POSTS_DIR.glob("*.md")):
        match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
        if not match:
            continue
        meta = yaml.safe_load(match.group(1)) or {}
        try:
            post_date = datetime.strptime(str(meta.get("date", "")), "%Y-%m-%d").date()
        except ValueError:
            post_date = None
        if post_date is None or post_date >= cutoff:
            metas.append(meta)
    return metas


def load_existing_source_urls() -> list[str]:
    urls: list[str] = []
    for meta in load_recent_posts_meta():
        title = meta.get("title", "")
        url = meta.get("source_url", "")
        if url:
            urls.append(url)
        if title or url:
            urls.append(f"- {title} ({url})")
    return urls


def load_recent_titles() -> list[str]:
    """直近 LOOKBACK_DAYS 日間の既存記事タイトル(タイトル類似度による重複判定用)。"""
    return [str(meta["title"]) for meta in load_recent_posts_meta() if meta.get("title")]


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
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError("トップレベルがJSON配列ではありません")
    return items


def slugify_fallback(item: dict, index: int) -> str:
    url_path = urlparse(item.get("source_url", "")).path.strip("/").split("/")[-1]
    candidate = re.sub(r"[^a-z0-9\-]+", "-", url_path.lower()).strip("-")
    if candidate:
        return candidate[:60]
    return f"article-{index}"


def _valid_date(value: object) -> str:
    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat() if re.match(r"^\d{4}-\d{2}-\d{2}$", text) else _today()
    except ValueError:
        return _today()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def normalize_item(item: object, index: int, seen_urls: set[str]) -> dict | None:
    """seen_urls は normalize_url 済みの集合。登録は採用確定後に呼び出し側が行う。"""
    if not isinstance(item, dict):
        print(f"::warning:: {index}件目: オブジェクトではないためスキップ ({item!r})", file=sys.stderr)
        return None

    missing = [k for k in REQUIRED_FIELDS if not item.get(k)]
    if missing:
        print(f"::warning:: {index}件目: 必須フィールド不足 {missing} のためスキップ", file=sys.stderr)
        return None

    source_url = str(item["source_url"]).strip()
    if normalize_url(source_url) in seen_urls:
        print(f"::warning:: {index}件目: source_urlが重複のためスキップ ({source_url})", file=sys.stderr)
        return None

    date_str = _valid_date(item["date"])

    slug = str(item.get("slug", "")).strip().lower()
    if not SLUG_RE.match(slug):
        slug = slugify_fallback(item, index)

    raw_tags = item.get("tags")
    tags = [str(t).strip() for t in (raw_tags if isinstance(raw_tags, list) else [])
            if str(t).strip() and str(t).strip().lower() not in BANNED_TAGS]

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


def select_items(
    raw_items: list[object],
    existing_urls: set[str],
    existing_titles: list[str],
    sources: set[str],
    url_checker: Callable[[str], UrlCheck],
) -> list[dict]:
    """AIが返した候補から、投稿してよい記事だけを選ぶ。

    判定順(安価なものから): 必須項目・URL重複 → タイトル類似 → 引用元照合 → 到達確認。
    sources が空(web_search の参照元が取れない)場合は、捏造URLを防げないため全件不採用にする。
    """
    if not sources:
        print("::warning:: web_search の参照元URLが取得できなかったため、今回は投稿しません", file=sys.stderr)
        return []

    seen_urls = {normalize_url(u) for u in existing_urls if u}
    accepted_titles = list(existing_titles)
    selected: list[dict] = []
    for i, raw_item in enumerate(raw_items, start=1):
        item = normalize_item(raw_item, i, seen_urls)
        if item is None:
            continue

        similar = find_similar_title(item["title"], accepted_titles)
        if similar:
            print(
                f"::warning:: {i}件目: 既存記事「{similar[0]}」とタイトルが類似"
                f"(類似度{similar[1]:.2f})のためスキップ ({item['title']})",
                file=sys.stderr,
            )
            continue

        if not is_cited(item["source_url"], sources):
            print(
                f"::warning:: {i}件目: source_urlがweb_searchの参照先に含まれないためスキップ ({item['source_url']})",
                file=sys.stderr,
            )
            continue

        check = url_checker(item["source_url"])
        if not check.ok:
            print(
                f"::warning:: {i}件目: source_urlに到達できないためスキップ [{check.reason}] ({item['source_url']})",
                file=sys.stderr,
            )
            continue
        if check.reason:
            print(f"{i}件目: 到達確認は判定不能でしたが採用します [{check.reason}] ({item['source_url']})")

        seen_urls.add(normalize_url(item["source_url"]))
        accepted_titles.append(item["title"])
        selected.append(item)
    return selected


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
        "posted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
        tool_choice="required",
        include=["web_search_call.action.sources"],
        reasoning={"effort": "low"},
        max_output_tokens=32000,
    )
    output_text = (resp.output_text or "").strip()
    if not output_text:
        status = getattr(resp, "status", "unknown")
        incomplete_reason = getattr(getattr(resp, "incomplete_details", None), "reason", None)
        print(
            f"エラー: AIから空の応答でした。(status={status}, incomplete_reason={incomplete_reason})",
            file=sys.stderr,
        )
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

    items = select_items(
        raw_items,
        existing_urls=existing_urls,
        existing_titles=load_recent_titles(),
        sources=extract_source_urls(resp),
        url_checker=check_url,
    )

    written: list[Path] = []
    for item in items:
        path = write_post(item)
        written.append(path)
        print(f"作成: {path.relative_to(ROOT)} ({item['title']})")

    print(f"\n合計 {len(written)} 件の記事を書き出しました。")


if __name__ == "__main__":
    main()
