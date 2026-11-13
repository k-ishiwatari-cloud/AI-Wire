"""まとめ記事の本文(Markdown のごく一部)を HTML にする。依存は標準ライブラリのみ。

まとめは AI が書くので、使える書式を次に絞り、それ以外はすべて文字としてエスケープする。
    ## 見出し / ### 小見出し(# は h2 に下げる。ページの h1 はまとめのタイトル)
    - 箇条書き / 1. 番号付き箇条書き
    空行で区切った段落、**太字**、[リンク](/posts/<ID>/ ・ /roundups/<ID>/ ・ https://…)

描画・リンクの抽出・文字数の計算は、同じブロック分割(_blocks)の結果を使う。
解釈がずれると、検査をすり抜けたリンクが描画されてしまうため。
"""
from __future__ import annotations

import re
from html import escape

# render_site.POST_ID_RE と同じ(render_site がこのモジュールを読み込むので、循環しないよう別に持つ)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_INLINE_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)|\*\*(.+?)\*\*")
_INTERNAL_LINK_RE = re.compile(r"^/(posts|roundups)/([^/]+)/?$")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\d+[.)]\s+(.*)$")

Block = tuple[str, list[str]]  # (タグ名, 中身の文字列)。h2/h3/p は 1 つ、ul/ol は項目ごと


def _blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    paragraph: list[str] = []
    items: list[str] = []
    list_tag = ""

    def flush() -> None:
        nonlocal list_tag
        if paragraph:
            # 日本語の文中で改行しても空白が入らないよう、行をそのままつなぐ
            blocks.append(("p", ["".join(paragraph)]))
            paragraph.clear()
        if items:
            blocks.append((list_tag, items.copy()))
            items.clear()
            list_tag = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if heading := _HEADING_RE.match(line):
            flush()
            blocks.append((f"h{max(2, len(heading.group(1)))}", [heading.group(2)]))
            continue
        bullet = _BULLET_RE.match(line)
        numbered = None if bullet else _NUMBERED_RE.match(line)
        if bullet or numbered:
            tag = "ul" if bullet else "ol"
            if paragraph or (items and list_tag != tag):
                flush()
            list_tag = tag
            items.append((bullet or numbered).group(1))
            continue
        if items:
            flush()
        paragraph.append(line)
    flush()
    return blocks


def _internal_link(url: str) -> tuple[str, str] | None:
    """(posts または roundups, ID)。内部リンクでなければ None。"""
    match = _INTERNAL_LINK_RE.match(url)
    if match and ID_RE.fullmatch(match.group(2)):
        return match.group(1), match.group(2)
    return None


def _inline(text: str) -> str:
    out, pos = [], 0
    for match in _INLINE_RE.finditer(text):
        out.append(escape(text[pos:match.start()]))
        label, url, bold = match.groups()
        if bold is not None:
            out.append(f"<strong>{escape(bold)}</strong>")
        elif link := _internal_link(url):
            out.append(f'<a href="/{link[0]}/{link[1]}/">{escape(label)}</a>')
        elif url.startswith(("https://", "http://")):
            out.append(f'<a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(label)}</a>')
        else:
            out.append(escape(label))  # 使えないリンクは文字だけ残す
        pos = match.end()
    out.append(escape(text[pos:]))
    return "".join(out)


def render_markdown(text: str) -> str:
    html = []
    for tag, parts in _blocks(text):
        if tag in ("ul", "ol"):
            lis = "\n".join(f"<li>{_inline(item)}</li>" for item in parts)
            html.append(f"<{tag}>\n{lis}\n</{tag}>")
        else:
            html.append(f"<{tag}>{_inline(parts[0])}</{tag}>")
    return "\n".join(html)


def inline_texts(text: str) -> list[str]:
    """見出し・段落・箇条書きの項目ごとの文字列(描画と同じ分割)。"""
    return [part for _, parts in _blocks(text) for part in parts]


def internal_links(text: str) -> list[tuple[str, str]]:
    """本文のサイト内リンク (posts または roundups, ID)。重複を除き、出てきた順。"""
    links: list[tuple[str, str]] = []
    for part in inline_texts(text):
        for match in _INLINE_RE.finditer(part):
            if match.group(2) and (link := _internal_link(match.group(2))) and link not in links:
                links.append(link)
    return links


def linked_ids(text: str) -> list[str]:
    """本文からリンクしている記事 ID(重複を除き、出てきた順)。"""
    return [i for kind, i in internal_links(text) if kind == "posts"]


def visible_length(text: str) -> int:
    """読者に見える文字数。リンク先の URL・Markdown の記号・空白は数えない。"""
    plain = "".join(_INLINE_RE.sub(lambda m: m.group(1) or m.group(3), part) for part in inline_texts(text))
    return len(re.sub(r"\s", "", plain))
