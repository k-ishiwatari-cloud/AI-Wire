"""記事一覧(site/index.html)・記事ページ(site/posts/<id>/)・まとめ記事(site/roundups/<id>/)・sitemap.xml を
静的 HTML として書き出す。

JavaScript を実行しないクローラー(AdSense の審査など)にも記事が見えるよう、ビルド時に描画する。
build_manifest.py から呼び出される。依存は標準ライブラリのみ。

site/index.html はテンプレートを兼ねる。<!-- build:NAME --> と <!-- /build:NAME --> の間を
ビルドのたびに置き換えるので、何度実行しても結果は同じになる。
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlparse

from roundup_markdown import render_markdown

BASE_URL = "https://ai-wire.site"
TAG_ORDER = ["Release", "Agent", "Benchmark", "Framework", "OSS", "Policy", "Research", "Safety", "Japan", "Other"]
WEEKDAYS = "月火水木金土日"
JST = timezone(timedelta(hours=9))
POST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SUMMARY_PREVIEW_CHARS = 15  # トップのカードに出す要約の文字数

# 記事ページの <head>。index.html / privacy.html と同じ解析・広告・アイコンを読み込む(パスは絶対パス)。
HEAD_ASSETS = """\
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<script src="/analytics.js"></script>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-F59NHKG7G0"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/style.css">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-7300454039947562"
     crossorigin="anonymous"></script>"""


FOOTER = """\
  <footer class="site-footer">
    <a href="/privacy">プライバシーポリシー</a>
  </footer>"""


def post_path(post: dict) -> str:
    return f"/posts/{post['id']}/"


def roundup_path(roundup: dict) -> str:
    return f"/roundups/{roundup['id']}/"


def format_date_heading(date_str: str) -> str:
    """例: 2026-10-29 -> 2026年10月29日(木)。解釈できなければそのまま返す。"""
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return date_str
    return f"{d.year}年{d.month}月{d.day}日({WEEKDAYS[d.weekday()]})"


def format_last_updated(generated_at: str) -> str:
    """ISO 8601(UTC)を日本時間の 2026/10/29 20:05 形式にする。閲覧者の時刻への変換は app.js が行う。"""
    d = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(JST)
    return d.strftime("%Y/%m/%d %H:%M")


def sort_tags(tags) -> list[str]:
    def key(tag: str):
        return (TAG_ORDER.index(tag), "") if tag in TAG_ORDER else (len(TAG_ORDER), tag.lower())
    return sorted(set(tags), key=key)


def summary_preview(summary: str) -> str:
    """トップのカード用に要約の先頭だけを残す。例: 一二三四五六七八九十一二三四五…"""
    summary = summary.strip()
    if len(summary) <= SUMMARY_PREVIEW_CHARS:
        return summary
    return summary[:SUMMARY_PREVIEW_CHARS].rstrip() + "…"


def render_card(post: dict, full: bool = False) -> str:
    """full=False はトップの一覧用(タイトルを記事ページへのリンクにし、要約は先頭だけ)。
    full=True は記事ページ用(要約の全文・本文・出典リンクを出す)。"""
    heading = "h1" if full else "h3"
    title = escape(post["title"])
    if not full:
        title = f'<a href="{post_path(post)}">{title}</a>'
    summary = post["summary"] if full else summary_preview(post["summary"])

    attrs = f' data-tags="{escape(json.dumps(post["tags"], ensure_ascii=False))}"'
    if post.get("posted_at"):
        attrs += f' data-posted-at="{escape(post["posted_at"])}"'

    tags_html = "".join(f'<span class="tag-pill">{escape(t)}</span>' for t in post["tags"])
    parts = [
        f'<article class="card"{attrs}>',
        '  <div class="card-top">',
        f'    <span>{escape(post["date"])}</span>',
        "  </div>",
        f'  <{heading} class="card-title">{title}</{heading}>',
    ]
    if tags_html:
        parts.append(f'  <div class="card-tags">{tags_html}</div>')
    parts.append(f'  <p class="card-summary">{escape(summary)}</p>')
    if full:
        if post.get("body"):
            parts.append(f'  <div class="card-body">{escape(post["body"])}</div>')
        parts += [
            f'  <a class="card-source" href="{escape(post["source_url"])}" target="_blank" rel="noopener noreferrer">',
            f'    {escape(post["source_name"])} で読む →',
            "  </a>",
        ]
    parts.append("</article>")
    return "\n".join(parts)


def _date_group(date_str: str, cards: list[str]) -> str:
    return "\n".join([
        '<section class="date-group">',
        f'<h2 class="date-heading">{escape(format_date_heading(date_str))}</h2>',
        *cards,
        "</section>",
    ])


def render_feed(posts: list[dict]) -> str:
    """posts は新しい順に並んでいる前提。同じ日付の記事を 1 つのグループにまとめる。"""
    if not posts:
        return '<p class="empty-state">該当する記事がまだありません。エージェントによる投稿をお待ちください。</p>'
    groups: dict[str, list[str]] = {}
    for post in sorted(posts, key=lambda p: p["date"], reverse=True):
        groups.setdefault(post["date"], []).append(render_card(post))
    # .date-block は画面外の描画を省略するための外枠。--cards は描画前の高さの見積もりに使う。
    # is-last はタイムラインの縦線を消す目印で、絞り込み時は app.js が付け替える
    blocks = []
    for i, (d, cards) in enumerate(groups.items()):
        cls = "date-block is-last" if i == len(groups) - 1 else "date-block"
        blocks.append(f'<div class="{cls}" style="--cards: {len(cards)}">\n{_date_group(d, cards)}\n</div>')
    return "\n".join(blocks)


def render_filters(posts: list[dict]) -> str:
    tags = sort_tags(t for p in posts for t in p["tags"])
    return "\n".join(
        f'<button class="filter-chip" data-tag="{escape(t)}" type="button">{escape(t)}</button>' for t in tags
    )


def _fill(html: str, name: str, content: str) -> str:
    pattern = re.compile(rf"(<!-- build:{name} -->).*?(<!-- /build:{name} -->)", re.DOTALL)
    if not pattern.search(html):
        raise ValueError(f"テンプレートに <!-- build:{name} --> の目印がありません")
    return pattern.sub(lambda m: m.group(1) + content + m.group(2), html, count=1)


def render_latest_roundup(roundups: list[dict]) -> str:
    """トップに出す最新のまとめ。roundups は新しい順に並んでいる前提。"""
    if not roundups:
        return ""
    latest = roundups[0]
    return "\n".join([
        "",
        '<section class="roundup-banner">',
        f'  <a class="roundup-banner-link" href="{roundup_path(latest)}">',
        f'    <span class="roundup-banner-title">{escape(latest["title"])}</span>',
        f'    <span class="roundup-banner-summary">{escape(latest["summary"])}</span>',
        "  </a>",
        '  <a class="roundup-banner-all" href="/roundups/">過去のまとめ →</a>',
        "</section>",
        "",
    ])


def render_index(template: str, posts: list[dict], generated_at: str, roundups: list[dict] = ()) -> str:
    last_updated = (f'<time id="last-updated" datetime="{escape(generated_at)}">'
                    f"{format_last_updated(generated_at)}</time>")
    html = _fill(template, "last-updated", last_updated)
    html = _fill(html, "roundup", render_latest_roundup(list(roundups)))
    html = _fill(html, "filters", "\n" + render_filters(posts) + "\n")
    return _fill(html, "feed", "\n" + render_feed(posts) + "\n")


def render_post_page(post: dict) -> str:
    main = f"""<main class="post-page">
  <p class="doc-back"><a href="/">← AI WIRE トップへ戻る</a></p>

<div class="date-block is-last" style="--cards: 1">
{_date_group(post["date"], [render_card(post, full=True)])}
</div>

{FOOTER}
</main>"""
    return _page(post["title"], post["summary"], post_path(post), main)


def _page(title: str, description: str, path: str, main: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)} — AI WIRE</title>
<meta name="description" content="{escape(description)}">
<link rel="canonical" href="{BASE_URL}{path}">
{HEAD_ASSETS}
</head>
<body>

{main}

<script src="/app.js"></script>
</body>
</html>
"""


def _period(roundup: dict) -> str:
    start, end = date.fromisoformat(roundup["period_start"]), date.fromisoformat(roundup["period_end"])
    end_text = f"{end.month}月{end.day}日" if end.year == start.year else f"{end.year}年{end.month}月{end.day}日"
    return f"{start.year}年{start.month}月{start.day}日〜{end_text}"


def render_roundup_page(roundup: dict) -> str:
    main = f"""<main class="doc roundup-page">
  <p class="doc-back"><a href="/">← AI WIRE トップへ戻る</a> ・ <a href="/roundups/">まとめ一覧</a></p>

  <h1>{escape(roundup["title"])}</h1>
  <p class="doc-meta">対象期間: {escape(_period(roundup))}</p>

  <div class="roundup-body">
{render_markdown(roundup["body"])}
  </div>

  <p class="roundup-note">このまとめは、AI WIRE に掲載した記事をもとに AI が作成し、編集者が確認して公開しています。
  個々のニュースの詳細は、リンク先の記事と出典をご覧ください。</p>

{FOOTER}
</main>"""
    return _page(roundup["title"], roundup["summary"], roundup_path(roundup), main)


def render_roundups_index(roundups: list[dict]) -> str:
    """roundups は新しい順に並んでいる前提。"""
    items = "\n".join(
        f'    <li><a href="{roundup_path(r)}">{escape(r["title"])}</a>'
        f'<p class="roundup-list-summary">{escape(r["summary"])}</p></li>'
        for r in roundups
    )
    main = f"""<main class="doc roundup-page">
  <p class="doc-back"><a href="/">← AI WIRE トップへ戻る</a></p>

  <h1>まとめ一覧</h1>
  <p class="doc-meta">AI WIRE に掲載した記事から、1 週間の流れをまとめています。</p>

  <ul class="roundup-list">
{items}
  </ul>

{FOOTER}
</main>"""
    return _page("まとめ一覧", "AI WIRE の週次まとめの一覧です。", "/roundups/", main)


def render_sitemap(posts: list[dict], roundups: list[dict] = ()) -> str:
    """記事の更新日時は管理していないので lastmod は出さない(ニュースの日付は更新日時ではない)。"""
    def url(path: str) -> str:
        return f"  <url><loc>{BASE_URL}{path}</loc></url>"

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        url("/"),
        url("/privacy"),
        *(url(post_path(p)) for p in posts),
        *([url("/roundups/")] if roundups else []),
        *(url(roundup_path(r)) for r in roundups),
        "</urlset>",
    ]
    return "\n".join(lines) + "\n"


def _is_web_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def write_site(posts: list[dict], generated_at: str, site_dir: Path, roundups: list[dict] = ()) -> None:
    """記事・まとめの ID と出典 URL はここで検査する。render_* を直接呼ぶ場合は呼び出し側で検査済みであること。
    roundups は新しい順に並んでいる前提。"""
    roundups = list(roundups)
    unsafe = [p["id"] for p in [*posts, *roundups] if not POST_ID_RE.fullmatch(p["id"])]
    if unsafe:
        raise ValueError(f"URL に使えない記事 ID があります: {unsafe}")
    bad_urls = [p["id"] for p in posts if not _is_web_url(p["source_url"])]
    if bad_urls:
        raise ValueError(f"出典 URL が http(s) ではない記事があります: {bad_urls}")

    index = site_dir / "index.html"
    index.write_text(render_index(index.read_text(encoding="utf-8"), posts, generated_at, roundups), encoding="utf-8")

    # 削除された記事のページが残らないよう、生成先を作り直す
    posts_dir = site_dir / "posts"
    shutil.rmtree(posts_dir, ignore_errors=True)
    for post in posts:
        page = posts_dir / post["id"] / "index.html"
        page.parent.mkdir(parents=True)
        page.write_text(render_post_page(post), encoding="utf-8")

    roundups_dir = site_dir / "roundups"
    shutil.rmtree(roundups_dir, ignore_errors=True)
    for roundup in roundups:
        page = roundups_dir / roundup["id"] / "index.html"
        page.parent.mkdir(parents=True)
        page.write_text(render_roundup_page(roundup), encoding="utf-8")
    if roundups:
        (roundups_dir / "index.html").write_text(render_roundups_index(roundups), encoding="utf-8")

    (site_dir / "sitemap.xml").write_text(render_sitemap(posts, roundups), encoding="utf-8")
