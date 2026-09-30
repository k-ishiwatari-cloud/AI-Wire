import pytest
from news_validation import UrlCheck

import generate_news
from generate_news import select_items


def _raw(title, url, slug="some-news"):
    return {
        "title": title,
        "date": "2026-09-28",
        "source_name": "Example",
        "source_url": url,
        "slug": slug,
        "tags": ["Research"],
        "summary": "要約。",
    }


def _ok(url):
    return UrlCheck(True, "")


DART_URL = "https://prtimes.jp/main/html/rd/p/000000922.000118641.html"
DART_BROKEN_URL = "https://www.docomo.ne.jp/info/news_release/topics/20260928_01.html"


def test_accepts_cited_reachable_new_item(recent_titles):
    items = select_items(
        [_raw("NTTドコモ、少データ環境で高精度予測するDARTを発表", DART_URL)],
        existing_urls=set(), existing_titles=recent_titles, sources={DART_URL}, url_checker=_ok,
    )
    assert [i["source_url"] for i in items] == [DART_URL]


def test_rejects_url_not_seen_by_web_search(recent_titles):
    items = select_items(
        [_raw("ドコモ、少データ下でも高精度予測を実現するAI技術を確立（DART）", DART_BROKEN_URL)],
        existing_urls=set(), existing_titles=recent_titles, sources={DART_URL}, url_checker=_ok,
    )
    assert items == []


def test_rejects_unreachable_url(recent_titles):
    checked = []

    def checker(url):
        checked.append(url)
        return UrlCheck(False, "HTTP 404")

    items = select_items(
        [_raw("NTTドコモ、少データ環境で高精度予測するDARTを発表", DART_URL)],
        existing_urls=set(), existing_titles=recent_titles, sources={DART_URL}, url_checker=checker,
    )
    assert items == []
    assert checked == [DART_URL]


def test_rejects_title_similar_to_existing_post_without_network(recent_titles):
    def checker(url):
        raise AssertionError("duplicate must be rejected before network access")

    items = select_items(
        [_raw("NTTドコモ、少データ環境で高精度予測するDARTを発表", DART_URL)],
        existing_urls=set(),
        existing_titles=recent_titles + ["ドコモ、少データ下でも高精度予測を実現するAI技術を確立（DART）"],
        sources={DART_URL},
        url_checker=checker,
    )
    assert items == []


def test_rejects_similar_titles_within_same_batch(recent_titles):
    other = "https://www.docomo.ne.jp/binary/pdf/info/news_release/topics_260928_c1.pdf"
    items = select_items(
        [
            _raw("NTTドコモ、少データ環境で高精度予測するDARTを発表", DART_URL, "a"),
            _raw("ドコモ、少データ下でも高精度予測を実現するAI技術を確立（DART）", other, "b"),
        ],
        existing_urls=set(), existing_titles=recent_titles, sources={DART_URL, other}, url_checker=_ok,
    )
    assert [i["slug"] for i in items] == ["a"]


def test_rejected_item_does_not_block_later_similar_item(recent_titles):
    """到達確認で落ちた記事のタイトルは、後続の同話題記事を重複扱いにしない。"""
    good = "https://www.docomo.ne.jp/binary/pdf/info/news_release/topics_260928_c1.pdf"

    def checker(url):
        return UrlCheck(url == good, "HTTP 404")

    items = select_items(
        [
            _raw("ドコモ、少データ下でも高精度予測を実現するAI技術を確立（DART）", DART_BROKEN_URL, "a"),
            _raw("NTTドコモ、少データ環境で高精度予測するDARTを発表", good, "b"),
        ],
        existing_urls=set(), existing_titles=recent_titles, sources={DART_BROKEN_URL, good}, url_checker=checker,
    )
    assert [i["slug"] for i in items] == ["b"]


def test_keeps_existing_exact_url_dedup(recent_titles):
    items = select_items(
        [_raw("全く別のタイトル", DART_URL)],
        existing_urls={DART_URL}, existing_titles=recent_titles, sources={DART_URL}, url_checker=_ok,
    )
    assert items == []


def test_load_recent_titles_respects_lookback(tmp_path, monkeypatch):
    monkeypatch.setattr(generate_news, "POSTS_DIR", tmp_path)
    (tmp_path / "old.md").write_text(
        "---\ntitle: 古い記事\ndate: '2000-01-01'\nsource_url: https://old.example\n---\n", encoding="utf-8")
    (tmp_path / "new.md").write_text(
        "---\ntitle: 新しい記事\ndate: '2999-01-01'\nsource_url: https://new.example\n---\n", encoding="utf-8")
    assert generate_news.load_recent_titles() == ["新しい記事"]


# ---- レビュー指摘への回帰テスト ----

def test_rejects_all_when_no_sources_were_returned(recent_titles):
    """web_search の参照元が取れない応答は、捏造URL投稿を防ぐため全件不採用にする。"""
    items = select_items(
        [_raw("NTTドコモ、少データ環境で高精度予測するDARTを発表", DART_URL)],
        existing_urls=set(), existing_titles=recent_titles, sources=set(), url_checker=_ok,
    )
    assert items == []


def test_url_dedup_uses_normalized_urls(recent_titles):
    items = select_items(
        [_raw("全く別のタイトル", DART_URL + "?utm_source=openai")],
        existing_urls={DART_URL + "/"}, existing_titles=recent_titles, sources={DART_URL}, url_checker=_ok,
    )
    assert items == []


def test_rejected_item_url_does_not_block_later_item_with_same_url(recent_titles):
    calls = []

    def checker(url):
        calls.append(url)
        return UrlCheck(len(calls) > 1, "一時的な404")

    items = select_items(
        [
            _raw("NTTドコモ、少データ環境で高精度予測するDARTを発表", DART_URL, "a"),
            _raw("NTTドコモ、少データ環境で高精度予測するDARTを発表", DART_URL, "b"),
        ],
        existing_urls=set(), existing_titles=recent_titles, sources={DART_URL}, url_checker=checker,
    )
    assert [i["slug"] for i in items] == ["b"]


@pytest.mark.parametrize("bad", ["文字列だけ", None, 123, ["list"]])
def test_non_dict_item_is_skipped_not_crashing(bad, recent_titles):
    items = select_items(
        [bad, _raw("NTTドコモ、少データ環境で高精度予測するDARTを発表", DART_URL)],
        existing_urls=set(), existing_titles=recent_titles, sources={DART_URL}, url_checker=_ok,
    )
    assert len(items) == 1


def test_non_list_tags_and_invalid_date_are_sanitized(recent_titles):
    raw = _raw("NTTドコモ、少データ環境で高精度予測するDARTを発表", DART_URL)
    raw["tags"] = "Research"
    raw["date"] = "2026-02-30"
    [item] = select_items(
        [raw], existing_urls=set(), existing_titles=recent_titles, sources={DART_URL}, url_checker=_ok,
    )
    assert item["tags"] == []
    assert item["date"] != "2026-02-30"


def test_extract_json_array_rejects_non_list():
    with pytest.raises(ValueError):
        generate_news.extract_json_array('```json\n{"title": "x"}\n```')
