"""週次まとめの下書きを作る処理(generate_roundup.py)を確認する。API は呼ばない。"""
import json
from datetime import date

import pytest

import generate_roundup as gr
import roundups


def _post(id_, date_, title="見出し", summary="要約。"):
    return {"id": id_, "title": title, "date": date_, "source_name": "Example", "source_url": "https://e.com/1",
            "tags": ["Release"], "summary": summary, "body": "", "posted_at": None}


WEEK = [
    _post("2026-10-26-gennai", "2026-10-26", "源内にエージェント機能", "デジタル庁は約18万人の職員向けに提供。"),
    _post("2026-10-28-s1", "2026-10-28", "AnthropicがS-1を提出", "NASDAQ上場に向けた準備。"),
]
ALL = [_post("2026-10-25-before", "2026-10-25"), *WEEK, _post("2026-11-02-after", "2026-11-02")]


def _body(chars=3500, links=("2026-10-26-gennai", "2026-10-28-s1")):
    link_text = "".join(f"[記事](/posts/{i}/)" for i in links)
    return f"## 今週の要点\n\n- {link_text}\n\n## テーマ\n\n" + "あ" * (chars - 2 * len(links) - 9)


# ---------------- 材料と指示 ----------------

def test_select_week_posts_keeps_monday_to_sunday():
    assert [p["id"] for p in gr.select_week_posts(ALL, "2026-w44")] == ["2026-10-26-gennai", "2026-10-28-s1"]


def test_prompt_contains_period_and_every_article():
    prompt = gr.build_prompt(WEEK, "2026-w44")
    assert "2026-10-26〜2026-11-01" in prompt
    assert "2026-11-02 以降" in prompt
    for p in WEEK:
        assert p["id"] in prompt and p["title"] in prompt and p["summary"] in prompt


def test_default_week_is_last_complete_week_in_jst():
    # 2026-11-01 22:05 UTC は日本時間で 11-02(月)07:05。先週(w44)を作る
    from datetime import datetime, timezone
    assert gr.default_week(datetime(2026, 11, 1, 22, 5, tzinfo=timezone.utc)) == "2026-w44"


# ---------------- 応答の読み取り ----------------

def test_parse_response_reads_summary_and_body():
    assert gr.parse_response(json.dumps({"summary": " 要約 ", "body": " 本文 "})) == ("要約", "本文")


@pytest.mark.parametrize("text", ["", "not json", "[]", '{"summary": "x"}', '{"summary": 1, "body": "b"}'])
def test_parse_response_rejects_malformed_output(text):
    with pytest.raises(ValueError):
        gr.parse_response(text)


# ---------------- 検査 ----------------

def test_good_draft_has_no_errors_or_warnings():
    errors, warnings = gr.check_roundup("今週の要約。", _body(), WEEK, ALL, "2026-w44")
    assert errors == [] and warnings == []


def test_links_to_unknown_posts_are_errors():
    errors, _ = gr.check_roundup("要約", _body(links=("2026-10-26-gennai", "2026-10-30-made-up")), WEEK, ALL, "2026-w44")
    assert any("2026-10-30-made-up" in e for e in errors)


def test_draft_without_any_post_link_is_an_error():
    errors, _ = gr.check_roundup("要約", _body(links=()), WEEK, ALL, "2026-w44")
    assert any("リンク" in e for e in errors)


def test_empty_summary_or_body_is_an_error():
    assert gr.check_roundup("", _body(), WEEK, ALL, "2026-w44")[0]
    assert gr.check_roundup("要約", "  ", WEEK, ALL, "2026-w44")[0]


def test_links_to_roundups_are_errors():
    """指示で使わないよう伝えている。存在の確認もしないので、公開前に止める。"""
    body = _body() + "\n\n[先週のまとめ](/roundups/2026-w43/)"
    errors, _ = gr.check_roundup("要約", body, WEEK, ALL, "2026-w44")
    assert any("/roundups/" in e for e in errors)


def test_links_outside_the_week_are_warnings():
    errors, warnings = gr.check_roundup("要約", _body(links=("2026-10-26-gennai", "2026-11-02-after")), WEEK, ALL, "2026-w44")
    assert errors == []
    assert any("2026-11-02-after" in w for w in warnings)


@pytest.mark.parametrize("chars", [2000, 6000])
def test_length_out_of_range_is_a_warning(chars):
    _, warnings = gr.check_roundup("要約", _body(chars=chars), WEEK, ALL, "2026-w44")
    assert any("字" in w for w in warnings)


def test_top_level_heading_and_external_links_are_warnings():
    body = "# タイトル\n\n" + _body() + "\n\n[外部](https://example.com/)"
    _, warnings = gr.check_roundup("要約", body, WEEK, ALL, "2026-w44")
    assert any("「#」" in w for w in warnings)
    assert any("外部" in w for w in warnings)


def test_numbers_not_found_in_the_articles_are_warnings():
    body = _body() + "\n\n職員は約18万人、上場時の評価額は3500億ドルとみられる。"
    _, warnings = gr.check_roundup("要約", body, WEEK, ALL, "2026-w44")
    joined = "\n".join(warnings)
    assert "3500" in joined
    assert "18" not in joined  # 記事の要約にある数字は問題にしない


def test_small_numbers_and_week_dates_are_not_reported():
    body = _body() + "\n\n3つのテーマ。10月26日から11月1日まで。"
    _, warnings = gr.check_roundup("要約", body, WEEK, ALL, "2026-w44")
    assert warnings == []


# ---------------- 書き出し ----------------

def test_build_roundup_fills_frontmatter():
    r = gr.build_roundup("2026-w44", "要約", "本文", "2026-11-01T22:05:00Z")
    assert r == {
        "id": "2026-w44", "kind": "weekly", "title": "週次まとめ 2026年10月26日〜11月1日",
        "period_start": "2026-10-26", "period_end": "2026-11-01", "summary": "要約", "body": "本文",
        "generated_at": "2026-11-01T22:05:00Z", "model": gr.MODEL,
    }


def test_report_lists_warnings_and_linked_posts():
    r = gr.build_roundup("2026-w44", "要約", _body(), "2026-11-01T22:05:00Z")
    report = gr.render_report(r, WEEK, ["文字数が多い"], attempts=2)
    assert "文字数が多い" in report
    assert "2 本中 2 本" in report
    assert "2 回目" in report


def test_report_says_when_there_are_no_warnings():
    r = gr.build_roundup("2026-w44", "要約", _body(), "2026-11-01T22:05:00Z")
    assert "機械的な検査で気になる点はありませんでした" in gr.render_report(r, WEEK, [], attempts=1)


# ---------------- 実行の流れ ----------------

class _FakeWriter:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    @property
    def calls(self):
        return len(self.prompts)

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.outputs.pop(0)


def _ok():
    return json.dumps({"summary": "要約", "body": _body()})


def test_generate_retries_once_when_the_draft_has_errors():
    writer = _FakeWriter([json.dumps({"summary": "要約", "body": _body(links=())}), _ok()])
    summary, body, warnings, attempts = gr.generate(WEEK, ALL, "2026-w44", writer)
    assert attempts == 2 and writer.calls == 2 and summary == "要約"
    # 2 回目は、1 回目の問題を伝えて書き直させる
    assert "リンクが 1 つもありません" not in writer.prompts[0]
    assert "リンクが 1 つもありません" in writer.prompts[1]


def test_generate_gives_up_after_two_bad_drafts():
    writer = _FakeWriter(["not json", json.dumps({"summary": "", "body": ""})])
    with pytest.raises(gr.DraftError):
        gr.generate(WEEK, ALL, "2026-w44", writer)


def test_run_writes_file_and_report(tmp_path):
    report = tmp_path / "report.md"
    path = gr.run("2026-w44", ALL, _FakeWriter([_ok()]), roundups_dir=tmp_path / "roundups",
                  report_path=report, now="2026-11-01T22:05:00Z")
    assert path == tmp_path / "roundups" / "2026-w44.md"
    assert roundups.parse_roundup(path)["summary"] == "要約"
    assert "週次まとめ 2026年10月26日〜11月1日" in report.read_text(encoding="utf-8")


def test_run_does_not_overwrite_an_existing_roundup(tmp_path):
    (tmp_path / "2026-w44.md").write_text("既存", encoding="utf-8")
    writer = _FakeWriter([_ok()])
    assert gr.run("2026-w44", ALL, writer, roundups_dir=tmp_path, report_path=None, now="x") is None
    assert writer.calls == 0
    assert (tmp_path / "2026-w44.md").read_text(encoding="utf-8") == "既存"


def test_run_skips_a_week_without_posts(tmp_path):
    writer = _FakeWriter([_ok()])
    assert gr.run("2026-w40", ALL, writer, roundups_dir=tmp_path, report_path=None, now="x") is None
    assert writer.calls == 0


def test_print_week_resolves_the_week_without_calling_the_api(capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["generate_roundup.py", "--print-week", "--week", "2026-w44"])
    gr.main()
    assert capsys.readouterr().out.strip() == "2026-w44"


def test_print_week_rejects_malformed_week(monkeypatch):
    monkeypatch.setattr("sys.argv", ["generate_roundup.py", "--print-week", "--week", "2026-44; rm -rf /"])
    with pytest.raises(SystemExit) as exc:
        gr.main()
    assert exc.value.code != 0


def test_report_for_existing_draft_rechecks_the_file(tmp_path):
    """PR だけを作り直すときに、ブランチにある下書きから検査結果を作り直す。"""
    r = gr.build_roundup("2026-w44", "要約", _body(chars=2000), "2026-11-01T22:05:00Z")
    path = tmp_path / "2026-w44.md"
    path.write_text(roundups.to_markdown(r), encoding="utf-8")
    report = gr.report_for_existing(path, ALL)
    assert "週次まとめ 2026年10月26日〜11月1日" in report
    assert "字です" in report  # 文字数の警告


def test_run_prints_warnings_to_the_log(tmp_path, capsys):
    body = _body(chars=2000)
    gr.run("2026-w44", ALL, _FakeWriter([json.dumps({"summary": "要約", "body": body})]),
           roundups_dir=tmp_path, report_path=None, now="2026-11-01T22:05:00Z")
    assert "字です" in capsys.readouterr().err
