"""まとめ記事(content/roundups/*.md)のファイル形式と、対象期間の決め方を確認する。"""
from datetime import date

import pytest

import roundups


# ---------------- 週の決め方 ----------------

def test_week_id_uses_iso_week():
    assert roundups.week_id(date(2026, 10, 26)) == "2026-w44"
    assert roundups.week_id(date(2026, 11, 1)) == "2026-w44"  # 日曜まで同じ週
    assert roundups.week_id(date(2026, 11, 2)) == "2026-w45"


def test_week_range_is_monday_to_sunday():
    assert roundups.week_range("2026-w44") == (date(2026, 10, 26), date(2026, 11, 1))


def test_week_that_spans_new_year_belongs_to_iso_year():
    assert roundups.week_id(date(2026, 12, 31)) == "2026-w53"
    assert roundups.week_range("2026-w53") == (date(2026, 12, 28), date(2027, 1, 3))


@pytest.mark.parametrize("bad", ["2026-44", "2026-w4", "2026-w54", "w44", "2026-W44"])
def test_week_range_rejects_malformed_ids(bad):
    with pytest.raises(ValueError):
        roundups.week_range(bad)


def test_previous_week_is_the_last_complete_week():
    assert roundups.previous_week(date(2026, 11, 2)) == "2026-w44"  # 月曜の朝に先週分を作る
    assert roundups.previous_week(date(2026, 11, 8)) == "2026-w44"  # 日曜はまだ今週が終わっていない


def test_weekly_title():
    assert roundups.weekly_title("2026-w44") == "週次まとめ 2026年10月26日〜11月1日"
    assert roundups.weekly_title("2026-w53") == "週次まとめ 2026年12月28日〜2027年1月3日"


# ---------------- ファイル形式 ----------------

def _roundup(**overrides):
    r = {
        "id": "2026-w44",
        "kind": "weekly",
        "title": "週次まとめ 2026年10月26日〜11月1日",
        "period_start": "2026-10-26",
        "period_end": "2026-11-01",
        "summary": "今週の要約。",
        "body": "## テーマ\n\n本文",
        "generated_at": "2026-11-01T22:05:00Z",
        "model": "gpt-5.6-luna",
    }
    r.update(overrides)
    return r


def test_file_round_trip(tmp_path):
    r = _roundup()
    path = tmp_path / "2026-w44.md"
    path.write_text(roundups.to_markdown(r), encoding="utf-8")
    assert roundups.parse_roundup(path) == r


def test_parse_rejects_missing_fields(tmp_path):
    path = tmp_path / "2026-w44.md"
    path.write_text("---\nkind: weekly\ntitle: t\n---\n本文\n", encoding="utf-8")
    with pytest.raises(ValueError, match="period_start"):
        roundups.parse_roundup(path)


def test_parse_rejects_unknown_kind(tmp_path):
    path = tmp_path / "2026-w44.md"
    path.write_text(roundups.to_markdown(_roundup(kind="hourly")), encoding="utf-8")
    with pytest.raises(ValueError, match="kind"):
        roundups.parse_roundup(path)


def test_parse_rejects_ids_unusable_in_urls(tmp_path):
    path = tmp_path / "2026 w44.md"
    path.write_text(roundups.to_markdown(_roundup()), encoding="utf-8")
    with pytest.raises(ValueError, match="ID"):
        roundups.parse_roundup(path)


@pytest.mark.parametrize("overrides, message", [
    ({"period_start": "2026-10-19"}, "期間"),        # 週 ID と期間が合わない
    ({"period_end": "2026-11-08"}, "期間"),
    ({"period_start": "2026-13-01"}, "日付"),        # 日付として読めない
    ({"body": "   "}, "本文"),
])
def test_parse_rejects_inconsistent_weekly_roundups(tmp_path, overrides, message):
    path = tmp_path / "2026-w44.md"
    path.write_text(roundups.to_markdown(_roundup(**overrides)), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        roundups.parse_roundup(path)


@pytest.mark.parametrize("name", ["not-a-week.md", "2025-w53.md"])  # 2025 年に第 53 週はない
def test_parse_rejects_weekly_roundups_with_invalid_week_ids(tmp_path, name):
    path = tmp_path / name
    path.write_text(roundups.to_markdown(_roundup()), encoding="utf-8")
    with pytest.raises(ValueError, match=name):
        roundups.parse_roundup(path)


def test_parse_rejects_frontmatter_that_is_not_a_mapping(tmp_path):
    path = tmp_path / "2026-w44.md"
    path.write_text("---\n- a\n- b\n---\n本文\n", encoding="utf-8")
    with pytest.raises(ValueError, match="2026-w44.md"):
        roundups.parse_roundup(path)


def test_load_roundups_sorts_newest_first(tmp_path):
    for rid, start, end in [("2026-w44", "2026-10-26", "2026-11-01"), ("2026-w45", "2026-11-02", "2026-11-08")]:
        (tmp_path / f"{rid}.md").write_text(
            roundups.to_markdown(_roundup(id=rid, period_start=start, period_end=end)), encoding="utf-8")
    assert [r["id"] for r in roundups.load_roundups(tmp_path)] == ["2026-w45", "2026-w44"]


def test_load_roundups_without_directory_is_empty(tmp_path):
    assert roundups.load_roundups(tmp_path / "missing") == []


# ---------------- 公開済みのまとめ ----------------

def test_published_roundups_link_only_to_existing_posts():
    """記事を削除・統合したときに、まとめのリンクが切れていないか。統合で転送している記事はよい。"""
    from build_manifest import POSTS_DIR
    from redirects import redirected_post_ids
    from roundup_markdown import internal_links

    published = roundups.load_roundups()
    reachable = {
        "posts": {p.stem for p in POSTS_DIR.glob("*.md")} | redirected_post_ids(),
        "roundups": {r["id"] for r in published},
    }
    broken = {r["id"]: [f"/{kind}/{i}/" for kind, i in internal_links(r["body"]) if i not in reachable[kind]]
              for r in published}
    assert not {rid: links for rid, links in broken.items() if links}
