"""運営者情報(サイトについて)ページを確認する。

サイトの目的・記事の作り方・運営者・問い合わせ先を、読者と AdSense の審査に分かる形で示す。
記事の作り方は実際の運用と食い違わないように書く(個別記事は自動で公開し、まとめは人が確認してから公開する)。
"""
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"
ABOUT = SITE / "about.html"
CONTACT_FORM = "https://forms.gle/pGr2BYTP1EEbjzEk7"


def _html() -> str:
    return ABOUT.read_text(encoding="utf-8")


def _main() -> str:
    html = _html()
    return html[html.index("<main"):html.index("</main>")]


def test_about_page_is_a_standalone_html_page():
    html = _html()
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert '<html lang="ja">' in html
    assert "<title>AI WIRE について — AI WIRE</title>" in html
    assert '<meta name="description" content="' in html
    assert '<link rel="canonical" href="https://ai-wire.site/about">' in html
    assert 'href="/style.css"' in html
    assert "noindex" not in html


def test_about_page_is_linked_from_top_and_privacy_pages():
    for name in ("index.html", "privacy.html"):
        assert 'href="/about"' in (SITE / name).read_text(encoding="utf-8"), name


def test_explains_operator_and_contact():
    main = _main()
    assert "AI WIRE 運営事務局" in main
    assert CONTACT_FORM in main
    assert 'href="/privacy"' in main


def test_explains_how_each_kind_of_article_is_made():
    main = _main()
    for heading in ("このサイトについて", "掲載している記事", "記事の作り方", "誤りの訂正", "運営者・お問い合わせ"):
        assert f"<h2>{heading}</h2>" in main, heading
    assert 'href="/roundups/"' in main
    assert "AI" in main


def test_does_not_claim_human_review_before_news_posts_are_published():
    """個別記事は bot が自動で公開している。公開前に人が確認しているとは書かない。"""
    main = _main()
    news = main[main.index("<h2>記事の作り方</h2>"):main.index("<h2>誤りの訂正</h2>")]
    assert "自動" in news
    assert "確認したうえで掲載" not in news
    assert "確認してから公開" in news  # まとめは人が確認してから公開する


def test_no_placeholders_left():
    assert "{{" not in _html()
