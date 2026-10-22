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
