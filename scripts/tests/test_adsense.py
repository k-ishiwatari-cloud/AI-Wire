"""Google AdSense のタグと ads.txt の設置を確認する。"""
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"

PUBLISHER_ID = "pub-7300454039947562"
ADSENSE_SRC = f"https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-{PUBLISHER_ID}"
# ads.txt の Google 認証局 ID(f08c47fec0942fa0)は Google 共通の固定値
ADS_TXT_LINE = f"google.com, {PUBLISHER_ID}, DIRECT, f08c47fec0942fa0"


def _head(name: str) -> str:
    html = (SITE / name).read_text(encoding="utf-8")
    return html[html.index("<head>"):html.index("</head>")]


def test_adsense_tag_is_in_head_of_content_pages():
    for name in ("privacy.html", "about.html"):  # トップ(index.html)はまとめがあるときだけ。test_render_site を参照
        head = _head(name)
        assert ADSENSE_SRC in head, name
        assert 'crossorigin="anonymous"' in head, name
        assert head.count("adsbygoogle.js") == 1, name


def test_adsense_tag_is_not_on_error_page():
    """Google のポリシー: エラーページなどコンテンツのない画面に広告を表示しない。"""
    assert "adsbygoogle" not in (SITE / "404.html").read_text(encoding="utf-8")


def test_ads_txt_authorizes_google_for_this_publisher():
    lines = [l.strip() for l in (SITE / "ads.txt").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    assert lines == [ADS_TXT_LINE]


def _rendered_heads():
    import sys
    sys.path.insert(0, str(SITE.parent / "scripts"))
    import render_site
    post = {"id": "a", "title": "t", "date": "2026-11-01", "source_name": "s", "source_url": "https://example.com/",
            "tags": [], "summary": "s", "body": "", "posted_at": "2026-11-01T00:00:00Z"}
    roundup = {"id": "2026-w44", "kind": "weekly", "title": "t", "period_start": "2026-10-26", "period_end": "2026-11-01",
               "summary": "s", "body": "## a\n\nb", "generated_at": "2026-11-02T00:00:00Z", "model": "m"}
    return render_site.render_post_page(post), [render_site.render_roundup_page(roundup),
                                                 render_site.render_roundups_index([roundup])]


def test_ads_are_not_on_auto_published_post_pages():
    """個別記事は人の確認なしに自動で公開する短い要約なので、広告を出さない。"""
    post_page, _ = _rendered_heads()
    assert "adsbygoogle" not in post_page


def test_ads_only_on_reviewed_roundup_body_pages():
    """広告は人が確認したまとめの本文ページにだけ出す。一覧は案内だけのページなので出さない。"""
    _, (roundup_page, roundups_index) = _rendered_heads()
    head = roundup_page[roundup_page.index("<head>"):roundup_page.index("</head>")]
    assert head.count(ADSENSE_SRC) == 1
    assert "adsbygoogle" not in roundups_index


def test_ads_are_not_on_news_list():
    assert "adsbygoogle" not in (SITE / "news.html").read_text(encoding="utf-8")
