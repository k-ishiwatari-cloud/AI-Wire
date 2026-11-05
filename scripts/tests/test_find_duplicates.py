import json
from pathlib import Path

import pytest

from find_duplicates import apply_merge, find_duplicate_groups, load_plan, render_report, to_plan
from redirects import parse_rule, post_id_of


def _post(id_, title, date="2026-09-10", url=None, body="", posted_at=None):
    return {
        "id": id_,
        "title": title,
        "date": date,
        "source_url": url or f"https://example.com/{id_}",
        "body": body,
        "posted_at": posted_at,
    }


def _ids(groups):
    return [[p["id"] for p in g] for g in groups]


# ---- 重複の検出 ----

def test_identical_titles_are_grouped(recent_titles):
    posts = [_post("a", "Google、Gemini 3.8 FlashをGA公開"), _post("b", "Google、Gemini 3.8 FlashをGA公開")]
    assert _ids(find_duplicate_groups(posts, corpus=recent_titles)) == [["a", "b"]]


def test_same_source_url_is_grouped_even_if_titles_differ(recent_titles):
    posts = [
        _post("a", "OpenAI、新しい推論モデルを公開", url="https://openai.com/news/x?utm_source=openai"),
        _post("b", "画像生成の料金体系を改定", url="https://openai.com/news/x"),
    ]
    assert _ids(find_duplicate_groups(posts, corpus=recent_titles)) == [["a", "b"]]


def test_unrelated_posts_are_not_grouped(recent_titles):
    posts = [_post("a", "Google、Gemini 3.8 FlashをGA公開"), _post("b", "経済産業省、AI事業者ガイドラインを改定")]
    assert find_duplicate_groups(posts, corpus=recent_titles) == []


def test_similar_titles_far_apart_in_time_are_not_grouped(recent_titles):
    """定例の発表(月次レポートなど)は同じ見出しでも別のニュース。"""
    posts = [
        _post("a", "Google、Gemini 3.8 FlashをGA公開", date="2026-08-01"),
        _post("b", "Google、Gemini 3.8 FlashをGA公開", date="2026-08-16"),
    ]
    assert find_duplicate_groups(posts, corpus=recent_titles) == []


def test_chained_duplicates_form_one_group(recent_titles):
    posts = [
        _post("a", "Google、Gemini 3.8 FlashをGA公開", url="https://example.com/1"),
        _post("b", "Google、Gemini 3.8 FlashをGA公開"),
        _post("c", "別の見出し", url="https://example.com/1/"),
    ]
    assert _ids(find_duplicate_groups(posts, corpus=recent_titles)) == [["a", "b", "c"]]


def test_excluded_post_leaves_its_group_and_the_rest_stay_grouped(recent_titles):
    """似ているだけの別ニュースを、確認したうえで外す。外しても他の記事の組み合わせは変わらない。"""
    posts = [
        _post("other", "Hugging Face、ブラウザ向けWebGPUカーネル群を公開", body="背景"),
        _post("a", "上院がOpenAIのHugging Face事案を調査開始"),
        _post("b", "上院がOpenAIのHugging Face事案を調査開始"),
    ]
    groups = find_duplicate_groups(posts, corpus=recent_titles, exclude={"other"})
    assert _ids(groups) == [["a", "b"]]


# ---- 残す記事(先頭)の選び方 ----

def test_post_with_body_is_kept(recent_titles):
    posts = [_post("a", "Google、Gemini 3.8 FlashをGA公開"), _post("b", "Google、Gemini 3.8 FlashをGA公開", body="背景")]
    assert _ids(find_duplicate_groups(posts, corpus=recent_titles)) == [["b", "a"]]


def test_earliest_posted_is_kept_when_bodies_are_equal(recent_titles):
    posts = [
        _post("a", "Google、Gemini 3.8 FlashをGA公開", posted_at="2026-09-11T03:00:00Z"),
        _post("b", "Google、Gemini 3.8 FlashをGA公開", posted_at="2026-09-10T03:00:00Z"),
        _post("c", "Google、Gemini 3.8 FlashをGA公開"),
    ]
    assert _ids(find_duplicate_groups(posts, corpus=recent_titles)) == [["b", "a", "c"]]


# ---- レポート ----

def test_report_lists_each_group_with_kept_post_marked(recent_titles):
    posts = [_post("a", "Google、Gemini 3.8 FlashをGA公開"), _post("b", "Google、Gemini 3.8 FlashをGA公開", body="背景")]
    report = render_report(find_duplicate_groups(posts, corpus=recent_titles))
    assert "1 組" in report
    kept = next(line for line in report.splitlines() if "`b`" in line)
    removed = next(line for line in report.splitlines() if "`a`" in line)
    assert "残す" in kept and "残す" not in removed


def test_posts_exactly_window_days_apart_are_grouped(recent_titles):
    posts = [
        _post("a", "Google、Gemini 3.8 FlashをGA公開", date="2026-08-01"),
        _post("b", "Google、Gemini 3.8 FlashをGA公開", date="2026-08-15"),
    ]
    assert _ids(find_duplicate_groups(posts, corpus=recent_titles, window_days=14)) == [["a", "b"]]


# ---- 確認済みの計画 ----

def _sha(*ids):
    return {id_: "0" * 64 for id_ in ids}


def test_plan_round_trips_through_file(tmp_path, recent_titles):
    """人が確認したレポートの内容をそのまま統合するため、計画をファイルに保存してから適用する。"""
    posts_dir = tmp_path / "posts"
    _write_posts(posts_dir, ["a", "b"])
    posts = [_post("a", "Google、Gemini 3.8 FlashをGA公開"), _post("b", "Google、Gemini 3.8 FlashをGA公開", body="背景")]
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(to_plan(find_duplicate_groups(posts, corpus=recent_titles), posts_dir)), encoding="utf-8")

    groups, hashes = load_plan(path)
    assert groups == [("b", ["a"])]
    assert sorted(hashes) == ["a", "b"]


@pytest.mark.parametrize("plan", [
    {"groups": [{"keep": "a", "remove": ["a"]}], "sha256": _sha("a")},
    {"groups": [{"keep": "a", "remove": ["b"]}, {"keep": "b", "remove": ["c"]}], "sha256": _sha("a", "b", "c")},
    {"groups": [{"keep": "a", "remove": ["c"]}, {"keep": "b", "remove": ["c"]}], "sha256": _sha("a", "b", "c")},
    {"groups": [{"keep": "a", "remove": []}], "sha256": _sha("a")},
    {"groups": [{"keep": "a", "remove": ["../../outside"]}], "sha256": _sha("a", "../../outside")},
    {"groups": [{"keep": "a", "remove": [1]}], "sha256": _sha("a", 1)},
    {"groups": [{"keep": "a", "remove": ["b"]}], "sha256": _sha("a")},
    {"groups": [{"keep": "a", "remove": "bc"}], "sha256": _sha("a", "b", "c")},
])
def test_inconsistent_plan_is_rejected(tmp_path, plan):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError):
        load_plan(path)


def test_merge_refuses_posts_edited_after_review(tmp_path, recent_titles):
    """確認した後に記事が書き換えられていたら(本文の追記など)、何も変更しない。"""
    posts_dir = tmp_path / "posts"
    _write_posts(posts_dir, ["keep", "dup"])
    redirects = tmp_path / "_redirects"
    plan_path = tmp_path / "plan.json"
    groups = [[_post("keep", "t"), _post("dup", "t")]]
    plan_path.write_text(json.dumps(to_plan(groups, posts_dir)), encoding="utf-8")
    (posts_dir / "dup.md").write_text("---\ntitle: dup\n---\n独自の解説\n", encoding="utf-8")

    with pytest.raises(ValueError):
        apply_merge(*load_plan(plan_path), posts_dir=posts_dir, redirects_path=redirects)
    assert (posts_dir / "dup.md").exists() and not redirects.exists()


# ---- 統合 ----

def _write_posts(posts_dir, ids):
    posts_dir.mkdir()
    for id_ in ids:
        (posts_dir / f"{id_}.md").write_text(f"---\ntitle: {id_}\n---\n", encoding="utf-8")


def test_merge_deletes_duplicates_and_redirects_to_kept_post(tmp_path):
    posts_dir = tmp_path / "posts"
    _write_posts(posts_dir, ["keep", "dup", "other"])
    redirects = tmp_path / "_redirects"

    apply_merge([("keep", ["dup"])], posts_dir=posts_dir, redirects_path=redirects)

    assert sorted(p.stem for p in posts_dir.glob("*.md")) == ["keep", "other"]
    lines = redirects.read_text(encoding="utf-8").splitlines()
    assert "/posts/dup/ /posts/keep/ 301" in lines
    assert "/posts/dup /posts/keep/ 301" in lines


def test_merge_keeps_existing_redirects_without_duplicating_lines(tmp_path):
    posts_dir = tmp_path / "posts"
    _write_posts(posts_dir, ["keep", "dup"])
    redirects = tmp_path / "_redirects"
    redirects.write_text("# 既存\n/posts/dup/ /posts/keep/ 301\n/old /privacy\n", encoding="utf-8")

    apply_merge([("keep", ["dup"])], posts_dir=posts_dir, redirects_path=redirects)

    lines = redirects.read_text(encoding="utf-8").splitlines()
    assert lines[:3] == ["# 既存", "/posts/dup/ /posts/keep/ 301", "/old /privacy"]
    assert lines.count("/posts/dup/ /posts/keep/ 301") == 1


@pytest.mark.parametrize("status", [" 301", ""])
def test_merge_retargets_old_redirects_pointing_at_removed_post(tmp_path, status):
    """以前 old → dup と転送していた場合、dup を消したら old も keep へ直接転送する(転送の連鎖を作らない)。"""
    posts_dir = tmp_path / "posts"
    _write_posts(posts_dir, ["keep", "dup"])
    redirects = tmp_path / "_redirects"
    redirects.write_text(f"/posts/old/ /posts/dup/{status}\n/posts/old /posts/dup{status}\n", encoding="utf-8")

    apply_merge([("keep", ["dup"])], posts_dir=posts_dir, redirects_path=redirects)

    lines = redirects.read_text(encoding="utf-8").splitlines()
    assert not any(parse_rule(line)[1].startswith("/posts/dup") for line in lines)
    assert f"/posts/old/ /posts/keep/{status}" in lines
    assert f"/posts/old /posts/keep/{status}" in lines


def test_merge_refuses_when_a_post_is_missing(tmp_path):
    """計画を作った後に記事が消えていたら、何も変更しない。"""
    posts_dir = tmp_path / "posts"
    _write_posts(posts_dir, ["keep", "dup"])
    redirects = tmp_path / "_redirects"

    with pytest.raises(FileNotFoundError):
        apply_merge([("keep", ["dup", "gone"])], posts_dir=posts_dir, redirects_path=redirects)
    assert (posts_dir / "dup.md").exists() and not redirects.exists()


def test_merge_rolls_back_when_deletion_fails(tmp_path, monkeypatch):
    posts_dir = tmp_path / "posts"
    _write_posts(posts_dir, ["keep", "dup1", "dup2"])
    redirects = tmp_path / "_redirects"
    redirects.write_text("# 既存\n", encoding="utf-8")

    real_unlink, real_write_bytes = Path.unlink, Path.write_bytes

    def flaky_unlink(self, *args, **kwargs):
        if self.name == "dup2.md":
            raise PermissionError(self)
        return real_unlink(self, *args, **kwargs)

    def flaky_write_bytes(self, *args, **kwargs):
        """読み取り専用の dup2.md は書き戻しもできない。消えていない記事を書き戻そうとしないこと。"""
        if self.name == "dup2.md":
            raise PermissionError(self)
        return real_write_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    monkeypatch.setattr(Path, "write_bytes", flaky_write_bytes)
    with pytest.raises(PermissionError):
        apply_merge([("keep", ["dup1", "dup2"])], posts_dir=posts_dir, redirects_path=redirects)

    assert sorted(p.stem for p in posts_dir.glob("*.md")) == ["dup1", "dup2", "keep"]
    assert (posts_dir / "dup1.md").read_text(encoding="utf-8") == "---\ntitle: dup1\n---\n"
    assert redirects.read_text(encoding="utf-8") == "# 既存\n"


# ---- _redirects ----

@pytest.mark.parametrize("line, expected", [
    ("/a /b 301", ("/a", "/b", "301")),
    ("/a /b", ("/a", "/b", None)),
    ("# コメント", None),
    ("", None),
])
def test_parse_rule(line, expected):
    assert parse_rule(line) == expected


@pytest.mark.parametrize("path, expected", [
    ("/posts/abc/", "abc"), ("/posts/abc", "abc"), ("/privacy", None), ("/posts/", None),
])
def test_post_id_of(path, expected):
    assert post_id_of(path) == expected


def test_post_redirects_do_not_hide_existing_posts():
    """本番の _redirects の記事転送が、存在する記事を隠したり、存在しない記事へ飛ばしたりしないこと。"""
    root = Path(__file__).resolve().parents[2]
    redirects = root / "site" / "_redirects"
    if not redirects.exists():
        return
    existing = {p.stem for p in (root / "content" / "posts").glob("*.md")}
    for line in redirects.read_text(encoding="utf-8").splitlines():
        rule = parse_rule(line)
        if not rule or post_id_of(rule[0]) is None:
            continue
        assert post_id_of(rule[0]) not in existing, line
        assert post_id_of(rule[1]) in existing, line
