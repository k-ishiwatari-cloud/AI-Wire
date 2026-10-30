"""記事一覧・記事ページ・sitemap をビルド時に静的 HTML として書き出す処理を確認する。

JavaScript を実行しないクローラー(AdSense の審査など)にも記事が見えるようにするため。
トップのカードは、以前 app.js が描画していたものと同じマークアップ・クラスで書き出す。
"""
import json
import re
import shutil
from pathlib import Path

import pytest

import render_site

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"


def _post(**overrides):
    post = {
        "id": "2026-10-29-sample-news",
        "title": "サンプル <記事> & タイトル",
        "date": "2026-10-29",
        "source_name": "Example News",
        "source_url": "https://example.com/news?a=1&b=2",
        "tags": ["Release", "Japan"],
        "summary": "要約の文章。",
        "body": "本文1行目\n本文2行目",
        "posted_at": "2026-10-29T20:11:57Z",
    }
    post.update(overrides)
    return post


# ---------------- 日付・タグ ----------------

def test_date_heading_matches_previous_client_format():
    assert render_site.format_date_heading("2026-10-29") == "2026年10月29日(木)"


def test_date_heading_falls_back_to_raw_string():
    assert render_site.format_date_heading("not-a-date") == "not-a-date"


def test_tags_follow_fixed_order_then_alphabetical():
    tags = ["Other", "zeta", "Japan", "Alpha", "Release"]
    assert render_site.sort_tags(tags) == ["Release", "Japan", "Other", "Alpha", "zeta"]


# ---------------- カード ----------------

LONG_SUMMARY = "一二三四五六七八九十一二三四五六七八九十。"  # 21 文字


def test_preview_card_links_title_and_shows_only_head_of_summary():
    """トップのカード: タイトルは記事ページへのリンク。要約は先頭 15 文字 + 「…」。本文と出典リンクは出さない。"""
    html = render_site.render_card(_post(summary=LONG_SUMMARY))
    assert html.startswith('<article class="card"')
    assert '<div class="card-top">' in html and "<span>2026-10-29</span>" in html
    assert ('<h3 class="card-title"><a href="/posts/2026-10-29-sample-news/">'
            "サンプル &lt;記事&gt; &amp; タイトル</a></h3>") in html
    assert '<span class="tag-pill">Release</span><span class="tag-pill">Japan</span>' in html
    assert '<p class="card-summary">一二三四五六七八九十一二三四五…</p>' in html
    assert "card-body" not in html
    assert "card-source" not in html and "example.com" not in html


def test_preview_keeps_short_summary_without_ellipsis():
    assert render_site.summary_preview("短い要約。") == "短い要約。"
    assert render_site.summary_preview("あ" * 15) == "あ" * 15
    assert render_site.summary_preview("あ" * 16) == "あ" * 15 + "…"


def test_preview_escapes_after_truncation():
    """15 文字で切ってからエスケープする(&amp; などの途中で切らない)。"""
    html = render_site.render_card(_post(summary="A&B" * 10))
    assert '<p class="card-summary">A&amp;BA&amp;BA&amp;BA&amp;BA&amp;B…</p>' in html


def test_full_card_on_post_page_shows_everything_without_self_link():
    html = render_site.render_card(_post(summary=LONG_SUMMARY), full=True)
    assert '<h1 class="card-title">サンプル &lt;記事&gt; &amp; タイトル</h1>' in html
    assert "/posts/" not in html
    assert f'<p class="card-summary">{LONG_SUMMARY}</p>' in html
    assert '<div class="card-body">本文1行目\n本文2行目</div>' in html
    assert ('<a class="card-source" href="https://example.com/news?a=1&amp;b=2" '
            'target="_blank" rel="noopener noreferrer">') in html
    assert "Example News で読む →" in html


def test_card_carries_data_for_client_side_filter_and_new_badge():
    html = render_site.render_card(_post(tags=['A"B', "C"]))
    tags = re.search(r'data-tags="([^"]*)"', html).group(1)
    assert json.loads(tags.replace("&quot;", '"')) == ['A"B', "C"]
    assert 'data-posted-at="2026-10-29T20:11:57Z"' in html


def test_card_omits_optional_parts():
    html = render_site.render_card(_post(tags=[], body="", posted_at=None), full=True)
    assert "card-tags" not in html
    assert "card-body" not in html
    assert "data-posted-at" not in html


# ---------------- 一覧 ----------------

def test_feed_groups_cards_by_date_newest_first():
    posts = [_post(id="b", date="2026-10-28"), _post(id="a", date="2026-10-29"), _post(id="c", date="2026-10-29")]
    html = render_site.render_feed(posts)
    headings = re.findall(r'<h2 class="date-heading">([^<]+)</h2>', html)
    assert headings == ["2026年10月29日(木)", "2026年10月28日(水)"]
    assert re.findall(r'href="/posts/([^/]+)/"', html) == ["a", "c", "b"]
    assert html.count('<section class="date-group">') == 2


def test_feed_wraps_each_date_group_for_lazy_rendering():
    """画面外の日付グループの描画を省略できるよう、グループごとに .date-block で包み、記事数を渡す。"""
    posts = [_post(id="a", date="2026-10-29"), _post(id="b", date="2026-10-29"), _post(id="c", date="2026-10-28")]
    html = render_site.render_feed(posts)
    assert re.findall(r'<div class="date-block[^"]*" style="--cards: (\d+)">\n<section class="date-group">', html) == ["2", "1"]


def test_last_date_block_is_marked_for_timeline_end():
    """縦線を消す最後のグループは、絞り込みで変わるためクラスで示す(初期表示はビルド時に付ける)。"""
    html = render_site.render_feed([_post(id="a", date="2026-10-29"), _post(id="b", date="2026-10-28")])
    assert re.findall(r'<div class="(date-block[^"]*)"', html) == ["date-block", "date-block is-last"]


def test_feed_shows_empty_state_without_posts():
    assert 'class="empty-state"' in render_site.render_feed([])


def test_filters_render_each_tag_once():
    html = render_site.render_filters([_post(tags=["Japan", "Release"]), _post(tags=["Release"])])
    assert re.findall(r'data-tag="([^"]+)"', html) == ["Release", "Japan"]
    assert 'class="filter-chip"' in html and 'type="button"' in html


def test_index_fills_build_markers_and_is_idempotent():
    template = (SITE / "index.html").read_text(encoding="utf-8")
    posts = [_post()]
    once = render_site.render_index(template, posts, "2026-10-29T11:05:00Z")
    twice = render_site.render_index(once, posts, "2026-10-29T11:05:00Z")
    assert once == twice
    assert once.count('<article class="card"') == 1
    assert 'data-tag="Release"' in once
    assert '<time id="last-updated" datetime="2026-10-29T11:05:00Z">2026/10/29 20:05</time>' in once


def test_index_has_canonical_url():
    assert '<link rel="canonical" href="https://ai-wire.site/">' in (SITE / "index.html").read_text(encoding="utf-8")


def test_index_template_has_build_markers():
    template = (SITE / "index.html").read_text(encoding="utf-8")
    for name in ("last-updated", "filters", "feed"):
        assert f"<!-- build:{name} -->" in template and f"<!-- /build:{name} -->" in template


def test_index_rejects_template_without_markers():
    with pytest.raises(ValueError):
        render_site.render_index("<html></html>", [_post()], "2026-10-29T11:05:00Z")


# ---------------- 記事ページ ----------------

def test_post_page_is_standalone_and_uses_absolute_paths():
    html = render_site.render_post_page(_post())
    assert html.lower().startswith("<!doctype html>")
    assert '<html lang="ja">' in html
    assert "<title>サンプル &lt;記事&gt; &amp; タイトル — AI WIRE</title>" in html
    assert '<meta name="description" content="要約の文章。">' in html
    assert '<link rel="canonical" href="https://ai-wire.site/posts/2026-10-29-sample-news/">' in html
    hrefs = re.findall(r'(?:href|src)="([^"]+)"', html)
    assert [h for h in hrefs if not h.startswith(("/", "https://"))] == []
    assert 'href="/"' in html and 'href="/privacy"' in html


def test_post_page_has_same_tags_as_other_pages():
    """解析・広告・アイコンは既存ページと同じものを読み込む。"""
    html = render_site.render_post_page(_post())
    index = (SITE / "index.html").read_text(encoding="utf-8")
    for tag in re.findall(r"<(?:script|link)\b[^>]*>", index):
        if 'rel="canonical"' in tag:
            continue
        tag =tag.replace('href="style.css"', 'href="/style.css"').replace('src="app.js"', 'src="/app.js"')
        assert tag in html, tag


def test_post_page_shows_the_card_in_a_date_group():
    html = render_site.render_post_page(_post())
    assert '<div class="date-block is-last" style="--cards: 1">\n<section class="date-group">' in html  # 縦線はカードで止める
    assert '<h2 class="date-heading">2026年10月29日(木)</h2>' in html
    assert '<h1 class="card-title">' in html
    assert 'class="card-source"' in html and '<div class="card-body">' in html  # 出典リンクと本文は記事ページにだけ出す


# ---------------- sitemap ----------------

def test_sitemap_lists_top_privacy_and_every_post():
    xml = render_site.render_sitemap([_post(id="a", date="2026-10-29"), _post(id="b", date="2026-10-28")])
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    locs = re.findall(r"<loc>([^<]+)</loc>", xml)
    assert locs == [
        "https://ai-wire.site/",
        "https://ai-wire.site/privacy",
        "https://ai-wire.site/posts/a/",
        "https://ai-wire.site/posts/b/",
    ]
    assert "<lastmod>" not in xml  # 記事の更新日時を管理していないため、不正確な lastmod は出さない


def test_robots_txt_points_to_sitemap():
    assert "Sitemap: https://ai-wire.site/sitemap.xml" in (SITE / "robots.txt").read_text(encoding="utf-8")


# ---------------- 書き出し ----------------

def _site_copy(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    shutil.copy(SITE / "index.html", site / "index.html")
    return site


def test_write_site_outputs_pages_and_removes_stale_ones(tmp_path):
    site = _site_copy(tmp_path)
    stale = site / "posts" / "deleted-post" / "index.html"
    stale.parent.mkdir(parents=True)
    stale.write_text("old", encoding="utf-8")

    render_site.write_site([_post(id="a"), _post(id="b")], "2026-10-29T11:05:00Z", site)

    assert (site / "posts" / "a" / "index.html").is_file()
    assert (site / "posts" / "b" / "index.html").is_file()
    assert not stale.exists()
    assert (site / "sitemap.xml").is_file()
    assert (site / "index.html").read_text(encoding="utf-8").count('<article class="card"') == 2


@pytest.mark.parametrize("post_id", ["../escape", "a/b", "ok\n", "-starts-with-hyphen"])
def test_write_site_rejects_unsafe_post_ids(tmp_path, post_id):
    site = _site_copy(tmp_path)
    with pytest.raises(ValueError):
        render_site.write_site([_post(id=post_id)], "2026-10-29T11:05:00Z", site)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "https://", "ftp://example.com/"])
def test_write_site_rejects_unsafe_source_urls(tmp_path, url):
    site = _site_copy(tmp_path)
    with pytest.raises(ValueError):
        render_site.write_site([_post(source_url=url)], "2026-10-29T11:05:00Z", site)


def test_generated_files_are_not_committed():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "site/posts/" in ignored
    assert "site/sitemap.xml" in ignored


# ---------------- app.js ----------------

def test_app_js_no_longer_renders_cards():
    """カードはビルド時に書き出すので、app.js は描画せず絞り込みだけを行う。"""
    js = (SITE / "app.js").read_text(encoding="utf-8")
    assert "manifest.json" not in js
    assert "innerHTML" not in js
    assert "data-tags" in js or "dataset.tags" in js
    assert 'closest(".date-block")' in js  # 絞り込みで空になった日付は、描画省略用の外枠ごと隠す
    assert '"is-last"' in js  # 表示中の最後のグループの縦線を消す


def test_preview_trims_space_at_cut_point():
    assert render_site.summary_preview("あいうえおかきくけこさしすせ そたちつて") == "あいうえおかきくけこさしすせ…"


def test_index_hides_body_and_source_which_stay_on_post_page():
    post = _post(summary=LONG_SUMMARY)
    index = render_site.render_index((SITE / "index.html").read_text(encoding="utf-8"), [post], "2026-10-29T11:05:00Z")
    page = render_site.render_post_page(post)
    for text in ("本文1行目", "Example News で読む →", LONG_SUMMARY):
        assert text not in index, text
        assert text in page, text
