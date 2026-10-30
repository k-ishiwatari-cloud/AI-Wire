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
    """@media の中身を除いた、常に適用される宣言だけの CSS。"""
    css = CSS
    for query in re.findall(r"@media[^{]+", CSS):
        css = css.replace(_media_block(query.strip()), "")
    return css


def test_feed_column_ignores_content_min_width():
    assert _declared(_top_level(), ".app", "grid-template-columns") == "272px minmax(0, 1fr)"


def test_feed_column_ignores_content_min_width_on_mobile():
    mobile = _media_block("@media (max-width: 860px)")
    assert _declared(mobile, ".app", "grid-template-columns") == "minmax(0, 1fr)"


def test_long_unbreakable_strings_wrap_inside_cards():
    assert _declared(_top_level(), ".card", "overflow-wrap") == "anywhere"


def test_scrollbar_space_is_always_reserved():
    """記事の少ないタグで縦スクロールバーが消えても、カード幅が変わらないようにする。"""
    assert _declared(_top_level(), "html", "scrollbar-gutter") == "stable"


def test_offscreen_date_blocks_skip_rendering():
    """記事が多くても初回の描画を軽くする(headless Edge では、大量の本文の初回レイアウトと重なると
    Web フォントの読み込み失敗が増えることも観測している)。"""
    css = _top_level()
    assert _declared(css, ".date-block", "content-visibility") == "auto"
    assert "var(--cards)" in _declared(css, ".date-block", "contain-intrinsic-size")


def test_date_block_leaves_room_for_timeline_dots():
    """描画の省略で .date-block の外側は切り取られるため、左にはみ出すタイムラインの丸印の分だけ余白を取り、
    同じ幅のマイナスマージンで位置を打ち消す。"""
    css = _top_level()
    pad = _declared(css, ".date-block", "padding-left")
    assert pad.endswith("px") and int(pad[:-2]) >= 4
    assert _declared(css, ".date-block", "margin-left") == f"-{pad}"


def test_date_block_comment_wording():
    """paint containment は描画中も効く。「省略中だけ切り取られる」という誤解を招く説明にしない。"""
    assert "省略中は" not in (Path(__file__).resolve().parents[2] / "site" / "style.css").read_text(encoding="utf-8")


def test_last_timeline_line_is_hidden_on_last_visible_block():
    """絞り込みで最後に表示されるグループが変わるため、:last-child ではなく is-last クラスで縦線を消す。"""
    assert ".date-block:last-child" not in CSS and ".date-group:last-child" not in CSS
    assert _declared(_top_level(), ".date-block.is-last .date-group", "border-left-color") == "transparent"


def test_print_renders_every_date_block():
    printing = _media_block("@media print")
    assert _declared(printing, ".date-block", "content-visibility") == "visible"


def test_card_has_no_extra_space_after_last_element():
    """トップのカードは要約で終わるため、最後の要素の下マージンでカードの下の余白が広がらないようにする。"""
    assert _declared(_top_level(), ".card > :last-child", "margin-bottom") == "0"
