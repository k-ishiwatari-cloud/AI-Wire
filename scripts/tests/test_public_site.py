"""一般公開サイトとしての設定(タイトル表記・検索エンジンへの公開)を確認する。"""
import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"


def _pages() -> list[Path]:
    return sorted(SITE.glob("*.html"))


def test_titles_do_not_say_internal():
    for page in _pages():
        title = re.search(r"<title>(.*?)</title>", page.read_text(encoding="utf-8")).group(1)
        assert "社内" not in title, page.name


def test_pages_are_indexable():
    for page in _pages():
        assert "noindex" not in page.read_text(encoding="utf-8").lower(), page.name


def test_headers_do_not_block_indexing():
    headers = (SITE / "_headers").read_text(encoding="utf-8").lower()
    assert "x-robots-tag" not in headers


def test_robots_txt_allows_all_crawlers():
    """AI クローラーの制限は Cloudflare の Bot Preference Sync が先頭に書き足すので、ここでは全許可のみ。"""
    lines = [l.strip() for l in (SITE / "robots.txt").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    assert lines[0] == "User-agent: *"
    assert "Allow: /" in lines
    assert not any(l.lower().startswith("disallow:") and l.split(":", 1)[1].strip() for l in lines)


def test_404_page_uses_absolute_paths():
    """404.html は任意の深さのパスで表示されるため、CSS やリンクは絶対パスで参照する。"""
    html = (SITE / "404.html").read_text(encoding="utf-8")
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert '<html lang="ja">' in html
    assert 'href="/style.css"' in html
    assert 'href="/"' in html
    hrefs = re.findall(r'(?:href|src)="([^"]+)"', html)
    relative = [h for h in hrefs if not h.startswith(("/", "https://", "http://", "#"))]
    assert relative == []
