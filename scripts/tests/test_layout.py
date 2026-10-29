"""記事の内容によってフィード列の幅が変わらないことを確認する。

grid の 1fr は minmax(auto, 1fr) と同じで、列の最小幅が中身の最小幅(min-content)になる。
長い URL など折り返せない文字列を含む記事が表示されると列が押し広げられ、
選択したタグによってカードの幅が変わってしまう。
"""
import re
from pathlib import Path

CSS = re.sub(r"/\*.*?\*/", "", (Path(__file__).resolve().parents[2] / "site" / "style.css").read_text(encoding="utf-8"), flags=re.S)


def _media_block(query: str) -> str:
    start = CSS.index("{", CSS.index(query)) + 1
    depth = 1
    for i in range(start, len(CSS)):
        depth += {"{": 1, "}": -1}.get(CSS[i], 0)
        if depth == 0:
            return CSS[start:i]
    raise AssertionError(query)


def _declared(css: str, selector: str, prop: str) -> str:
    """css 内で selector に最後に宣言された prop の値(後勝ち)。"""
    values = []
    for body in re.findall(r"(?:^|[}\s])" + re.escape(selector) + r"\s*\{([^}]*)\}", css):
        values += re.findall(r"(?:^|;)\s*" + re.escape(prop) + r"\s*:\s*([^;]+)", body)
    assert values, f"{selector} {{ {prop} }}"
    return " ".join(values[-1].split())


def _top_level() -> str:
    return CSS.replace(_media_block("@media (max-width: 860px)"), "")


def test_feed_column_ignores_content_min_width():
    assert _declared(_top_level(), ".app", "grid-template-columns") == "272px minmax(0, 1fr)"


def test_feed_column_ignores_content_min_width_on_mobile():
    mobile = _media_block("@media (max-width: 860px)")
    assert _declared(mobile, ".app", "grid-template-columns") == "minmax(0, 1fr)"


def test_long_unbreakable_strings_wrap_inside_cards():
    assert _declared(_top_level(), ".card", "overflow-wrap") == "anywhere"
