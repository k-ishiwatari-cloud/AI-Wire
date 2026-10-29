"""ファビコン・アプリアイコン・ロゴの設置を確認する。"""
import json
import struct
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"
PAGES = ("index.html", "privacy.html", "404.html")

# 404.html は任意の深さのパスで表示されるため、すべて絶対パスで参照する
HEAD_LINKS = (
    '<link rel="icon" href="/favicon.ico" sizes="48x48">',
    '<link rel="icon" href="/favicon.svg" type="image/svg+xml">',
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
    '<link rel="manifest" href="/site.webmanifest">',
)


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    return struct.unpack(">II", data[16:24])


def _head(name: str) -> str:
    html = (SITE / name).read_text(encoding="utf-8")
    return html[html.index("<head>"):html.index("</head>")]


def test_every_page_declares_icons():
    for name in PAGES:
        head = _head(name)
        for link in HEAD_LINKS:
            assert link in head, (name, link)


def test_icon_files_exist_with_expected_sizes():
    assert (SITE / "favicon.svg").read_text(encoding="utf-8").lstrip().startswith("<svg")
    ico = (SITE / "favicon.ico").read_bytes()
    count = struct.unpack("<H", ico[4:6])[0]
    assert sorted((ico[6 + 16 * i] or 256) for i in range(count)) == [16, 32, 48]
    assert _png_size(SITE / "apple-touch-icon.png") == (180, 180)
    assert _png_size(SITE / "icons" / "app-icon-192.png") == (192, 192)
    assert _png_size(SITE / "icons" / "app-icon-512.png") == (512, 512)


def test_webmanifest_references_existing_icons():
    manifest = json.loads((SITE / "site.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "AI WIRE"
    sizes = set()
    for icon in manifest["icons"]:
        path = SITE / icon["src"].lstrip("/")
        w, h = _png_size(path)
        assert icon["sizes"] == f"{w}x{h}"
        sizes.add(icon["sizes"])
    assert {"192x192", "512x512"} <= sizes


def test_sidebar_shows_logo_mark():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert '<img class="wordmark-mark" src="/favicon.svg" alt=""' in html
