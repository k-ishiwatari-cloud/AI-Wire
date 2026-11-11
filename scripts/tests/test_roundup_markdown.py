"""まとめ記事の本文(Markdown のごく一部)を HTML にする処理を確認する。

まとめは AI が書くので、使える書式を絞り、それ以外はすべて文字としてエスケープする。
"""
import pytest

from roundup_markdown import linked_ids, render_markdown, visible_length


def test_headings_paragraphs_and_lists():
    html = render_markdown("## テーマ1\n\n段落の1行目\n2行目\n\n- 項目A\n- 項目B\n\n### 小見出し\n\n1. 一つ目\n2. 二つ目")
    assert html == (
        "<h2>テーマ1</h2>\n"
        "<p>段落の1行目2行目</p>\n"
        "<ul>\n<li>項目A</li>\n<li>項目B</li>\n</ul>\n"
        "<h3>小見出し</h3>\n"
        "<ol>\n<li>一つ目</li>\n<li>二つ目</li>\n</ol>"
    )


def test_top_level_heading_is_rendered_as_h2():
    """ページの h1 はまとめのタイトルなので、本文の # は h2 に下げる。"""
    assert render_markdown("# 見出し") == "<h2>見出し</h2>"


def test_internal_links_and_bold():
    html = render_markdown("**重要**：[源内の記事](/posts/2026-10-26-gennai/)を参照")
    assert html == '<p><strong>重要</strong>：<a href="/posts/2026-10-26-gennai/">源内の記事</a>を参照</p>'


def test_external_https_links_are_kept_with_noopener():
    html = render_markdown("[公式](https://example.com/a?b=1&c=2)")
    assert html == ('<p><a href="https://example.com/a?b=1&amp;c=2" target="_blank" '
                    'rel="noopener noreferrer">公式</a></p>')


@pytest.mark.parametrize("url", ["javascript:alert(1)", "/posts/../secret/", "data:text/html,x", "//evil.example/"])
def test_unsafe_links_are_rendered_as_plain_text(url):
    html = render_markdown(f"[押して]({url})")
    assert "<a" not in html
    assert "押して" in html


def test_html_is_escaped():
    html = render_markdown("<script>alert(1)</script> & **<b>太字</b>**")
    assert "<script>" not in html and "<b>" not in html
    assert "&lt;script&gt;" in html and "&amp;" in html
    assert "<strong>&lt;b&gt;太字&lt;/b&gt;</strong>" in html


def test_linked_ids_lists_post_ids_in_order_without_duplicates():
    text = "[a](/posts/2026-10-26-a/) と [b](/posts/2026-10-27-b) と [a2](/posts/2026-10-26-a/) [x](https://example.com/posts/z/)"
    assert linked_ids(text) == ["2026-10-26-a", "2026-10-27-b"]


def test_visible_length_counts_text_but_not_urls_markup_or_spaces():
    text = "## 見出し\n\n- [記事](/posts/2026-10-26-long-identifier/)を **読む**\n"
    assert visible_length(text) == len("見出し記事を読む")


def test_id_pattern_matches_render_site():
    import render_site
    import roundup_markdown
    assert roundup_markdown.ID_RE.pattern == render_site.POST_ID_RE.pattern


def test_link_split_across_lines_is_checked_the_same_way_it_is_rendered():
    """描画と検査で解釈がずれると、存在しない記事へのリンクが検査をすり抜ける。"""
    text = "[リンク](/posts/\nmissing/)"
    assert '<a href="/posts/missing/">' in render_markdown(text)
    assert linked_ids(text) == ["missing"]


def test_internal_links_include_roundups():
    from roundup_markdown import internal_links
    text = "[記事](/posts/a/) [まとめ](/roundups/2026-w43/) [外部](https://example.com/)"
    assert internal_links(text) == [("posts", "a"), ("roundups", "2026-w43")]
