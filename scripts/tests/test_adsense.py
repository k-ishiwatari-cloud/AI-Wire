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
    for name in ("index.html", "privacy.html"):
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
