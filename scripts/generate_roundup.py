#!/usr/bin/env python3
"""先週の記事から週次まとめの下書きを作り、content/roundups/<週ID>.md に書く。

公開前に人が確認する前提(GitHub Actions が PR にする。.github/workflows/weekly_roundup.yml)。
機械的な検査で見つかった気になる点は --report のファイルに書き、PR の本文に載せる。

使い方:
    python scripts/generate_roundup.py                         # 最後に終わった週(日本時間)
    python scripts/generate_roundup.py --week 2026-w44 --report report.md
必要な環境変数: OPENAI_API_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from build_manifest import POSTS_DIR, parse_post
from news_validation import content_digest_reason
from roundup_markdown import inline_texts, internal_links, linked_ids, visible_length
from roundups import ROUNDUPS_DIR, parse_roundup, previous_week, to_markdown, week_range, weekly_title

MODEL = os.environ.get("ROUNDUP_MODEL", "gpt-5.6-luna")
MIN_CHARS, MAX_CHARS = 3000, 5000
MAX_ATTEMPTS = 2
JST = timezone(timedelta(hours=9))

INSTRUCTIONS = """あなたは日本語の AI ニュースサイト「AI WIRE」の編集者です。
以下は {start}〜{end} の週にサイトに載せた記事の一覧です。これをもとに、読者向けの「週次まとめ」を書いてください。

## 読者
AI の動向を仕事で追っている日本のビジネスパーソンとエンジニア。個々のニュースは見出しで知っているが、
全体の流れと「結局何が起きているのか」をつかみたい。

## 書くこと
JSON で summary と body を返す。
- summary: まとめ全体を 1〜2 文(120 字以内)で。一覧ページと検索結果に出る。
- body: 本文(Markdown)。次の構成で書く。
  1. 「## 今週の要点」として 3〜5 個の箇条書き。
  2. 今週の大きな流れを、根拠を確保できる 2〜4 個のテーマにまとめ、テーマごとに「## 」の見出しを立てて解説する。
     個々のニュースを並べ直すのではなく、つながりと意味(なぜ重要か、誰に影響するか)を書く。
  3. 「## {next_start} 以降の注目点」として 2〜3 個。一覧にない開催・公開・提供の予定は作らず、
     「〜の提供範囲が明らかになるか」のような確かめるべき点として書く。
- 本文は全体で {min_chars:,}〜{max_chars:,} 字(リンク先の URL は数えない)。
- 使える書式は「## 見出し」「### 小見出し」「- 箇条書き」「**太字**」「[文中の語句](/posts/記事ID/)」だけ。
  「# 」の見出し(ページのタイトルはサイトが付ける)、表、外部サイトへのリンクは使わない。
- 根拠にした記事へのリンクは、文中でその出来事を述べている語句に付ける。記事 ID は一覧にあるものだけを使う。
  良い例: A社は[新しいモデルの公開](/posts/記事ID/)を発表した。
  悪い例: A社は新しいモデルの公開を発表した。[A社が新モデルを公開](/posts/記事ID/)
  文や段落の末尾にリンクだけを並べない。リンクだけの段落や箇条書きも作らない。
  (例の会社名・出来事は説明のためのもので、本文には使わない)

## 書き方
- 傾向や変化を言い切らない。「〜へ広がった」「〜の段階に入った」「〜の局面に入った」「〜が加速している」
  「〜が定着した」のような書き方をせず、今週の記事で確認できた具体的な事実と、その範囲を書く。
  良い例: 今週掲載した記事では、A社とB社がそれぞれエージェントの接続管理の製品を発表した。
  悪い例: エージェントは業務システムの管理対象になる段階に入った。
- 事実から読み取れることを書く場合は、根拠の範囲を示したうえで「〜の可能性がある」「〜とみられる」を使う。
- 「今週の要点」と summary も同じ。出来事の事実(誰が何を発表したか)は言い切ってよい。

## 守ること
- 事実は一覧の記事に書かれていることだけを使う。一覧にない数字・固有名詞・出来事・過去との比較を足さない。
- 背景や意味づけは、根拠の事実と記事リンクを示したうえで、その事実から何が言えるかとして書く。
  記載のない原因や企業の意図は補わない。因果関係が確認できない出来事どうしを因果で結ばない。
- 推測は「〜とみられる」「〜の可能性がある」など推測と分かる書き方にする。ただし推測の書き方をすれば
  根拠のない話を書いてよいわけではない。
- 同じ発表の転載・解説・続報は 1 つの出来事として数える。記事の本数を、出来事の多さや傾向の強さの根拠にしない。
- 1 つの出来事しか根拠がない話を、業界全体の傾向のように書かない。
- 企業の自己申告の数値や評価は「〜社によると」と出どころを付ける。
- テーマに入らない記事は無理に入れなくてよい。

## 記事一覧({count} 本)
{articles}
"""

RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "weekly_roundup",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}, "body": {"type": "string"}},
        "required": ["summary", "body"],
        "additionalProperties": False,
    },
}

RETRY_NOTE = """

## 前回の下書きの問題
前回あなたが書いた下書きには次の問題があり、使えませんでした。上の指示に沿って、問題のない下書きを書き直してください。
{problems}
"""

Writer = Callable[[str], str]  # 指示を受け取り、モデルの出力(JSON 文字列)を返す


class DraftError(RuntimeError):
    """何度書かせても公開の前提を満たす下書きにならなかった。"""


# ---- 材料と指示 ----

def default_week(now: datetime) -> str:
    return previous_week(now.astimezone(JST).date())


def select_week_posts(posts: list[dict], rid: str) -> list[dict]:
    """対象週の記事。記事そのものが他サイトのまとめのもの(削除候補)は材料にしない。"""
    start, end = week_range(rid)
    week = [
        p for p in posts
        if start <= date.fromisoformat(p["date"]) <= end and not content_digest_reason(p["title"], p["source_url"])
    ]
    return sorted(week, key=lambda p: (p["date"], p["id"]))


def build_prompt(week_posts: list[dict], rid: str) -> str:
    start, end = week_range(rid)
    articles = "\n\n".join(
        f"### {p['title']}\n- 記事ID: {p['id']}\n- 日付: {p['date']}\n- 出典: {p['source_name']}\n"
        f"- タグ: {', '.join(p['tags'])}\n- 要約: {p['summary']}"
        for p in week_posts
    )
    return INSTRUCTIONS.format(
        start=start, end=end, next_start=end + timedelta(days=1), min_chars=MIN_CHARS, max_chars=MAX_CHARS,
        count=len(week_posts), articles=articles,
    )


# ---- 応答の読み取りと検査 ----

def parse_response(text: str) -> tuple[str, str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON として読めませんでした: {exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str) for k in ("summary", "body")):
        raise ValueError("summary と body の文字列がそろっていません")
    return data["summary"].strip(), data["body"].strip()


_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_LINK_URL_RE = re.compile(r"\]\([^)]*\)")
_EXTERNAL_LINK_RE = re.compile(r"\]\((?:https?:)?//")
_LINK_RE = re.compile(r"\[[^\]]+\]\([^)\s]+\)")
# リンクを \0 に置き換えた文字列で、段落の頭か文の終わり(。)のあとに、リンクと区切りの記号しか続かない
# (根拠を文中ではなく末尾に並べた。リンクだけの段落も含む)
_TRAILING_LINKS_RE = re.compile(r"(?:^|[。．])[\s、,，・()（）]*\0[\s\0、,，・()（）。．]*$")
# 傾向を言い切る言い回し。指示で避けるよう伝えているが、残っていれば確認してもらう
_STRONG_ASSERTION_RE = re.compile(r"広がった|段階に入った|局面に入った|加速している|定着した")


def _normalize_number(n: str) -> str:
    """3,500 → 3500、09 → 9(日付の 2026-11-09 と 11月9日 を同じ数として扱う)。"""
    n = n.replace(",", "")
    return n if "." in n else str(int(n))


def _numbers(text: str) -> set[str]:
    text = unicodedata.normalize("NFKC", text)
    return {_normalize_number(n) for n in _NUMBER_RE.findall(text)}


def _unsourced_numbers(body: str, sources: list[dict], rid: str) -> list[str]:
    """本文の数字のうち、材料の記事のどこにも出てこないもの。1 桁の数と、対象週の日付は除く。"""
    known = _numbers(" ".join(f"{p['title']} {p['summary']}" for p in sources))
    start, end = week_range(rid)
    for d in (start + timedelta(days=i) for i in range((end - start).days + 2)):
        known |= {str(d.year), str(d.month), str(d.day)}
    found = _numbers(_LINK_URL_RE.sub("]", body))
    return sorted(n for n in found - known if len(n.replace(".", "")) >= 2)


def check_roundup(summary: str, body: str, week_posts: list[dict], all_posts: list[dict],
                  rid: str) -> tuple[list[str], list[str]]:
    """(公開できない問題, 確認してほしい点)。"""
    errors: list[str] = []
    warnings: list[str] = []
    if not summary:
        errors.append("要約(summary)が空です")
    if not body:
        errors.append("本文(body)が空です")
        return errors, warnings

    known = {p["id"] for p in all_posts}
    week_ids = {p["id"] for p in week_posts}
    if roundup_links := [f"/roundups/{i}/" for kind, i in internal_links(body) if kind == "roundups"]:
        errors.append(f"まとめへのリンクは使えません(存在を確認できないため): {roundup_links}")
    ids = linked_ids(body)
    if not ids:
        errors.append("本文に記事へのリンクが 1 つもありません")
    unknown = [i for i in ids if i not in known]
    if unknown:
        errors.append(f"存在しない記事へのリンクがあります: {unknown}")
    by_id = {p["id"]: p for p in all_posts}
    digests = [i for i in ids if i in by_id and content_digest_reason(by_id[i]["title"], by_id[i]["source_url"])]
    if digests:
        errors.append(f"他サイトのまとめにあたる記事は根拠に使えません: {digests}")
    outside = [i for i in ids if i in known and i not in week_ids and i not in digests]
    if outside:
        warnings.append(f"対象週以外の記事にリンクしています: {outside}")

    length = visible_length(body)
    if not MIN_CHARS <= length <= MAX_CHARS:
        warnings.append(f"本文が {length:,} 字です(目安は {MIN_CHARS:,}〜{MAX_CHARS:,} 字)")
    if any(line.startswith("# ") for line in body.splitlines()):
        warnings.append("本文に「#」の見出しがあります(ページのタイトルと重なるので h2 として表示します)")
    if _EXTERNAL_LINK_RE.search(body):
        warnings.append("外部サイトへのリンクがあります。リンク先が正しいか確認してください")
    if len(summary) > 160:
        warnings.append(f"要約が {len(summary)} 字です(目安は 120 字以内)")
    trailing = sum(1 for part in inline_texts(body) if _TRAILING_LINKS_RE.search(_LINK_RE.sub("\0", part)))
    if trailing:
        warnings.append(f"文の末尾にリンクだけを並べた段落が {trailing} か所あります(リンクは文中の語句に付ける)")
    if strong := sorted({m.group(0) for m in _STRONG_ASSERTION_RE.finditer(f"{summary}\n{body}")}):
        warnings.append(f"傾向を言い切る言い回しがあります(控えめな表現にできないか確認してください): {', '.join(strong)}")

    sources = [p for p in all_posts if p["id"] in week_ids | set(ids)]
    if numbers := _unsourced_numbers(f"{summary}\n{body}", sources, rid):
        warnings.append(f"材料の記事に見当たらない数字があります(事実か確認してください): {', '.join(numbers)}")
    return errors, warnings


# ---- 生成 ----

def openai_writer(model: str = MODEL) -> Writer:
    from openai import OpenAI

    client = OpenAI()

    def write(prompt: str) -> str:
        resp = client.responses.create(
            model=model,
            input=prompt,
            reasoning={"effort": "high"},
            text={"format": RESPONSE_FORMAT},
            max_output_tokens=32000,
        )
        if resp.status != "completed":
            raise ValueError(f"生成が完了しませんでした(status={resp.status}, {resp.incomplete_details})")
        usage = resp.usage
        print(f"トークン: 入力 {usage.input_tokens:,} / 出力 {usage.output_tokens:,}", file=sys.stderr)
        return resp.output_text or ""

    return write


def generate(week_posts: list[dict], all_posts: list[dict], rid: str,
             writer: Writer) -> tuple[str, str, list[str], int]:
    """(要約, 本文, 確認してほしい点, 試行回数)。公開できない問題が残れば、問題を伝えて 1 回だけ書き直させる。"""
    base_prompt = build_prompt(week_posts, rid)
    prompt = base_prompt
    problems: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if problems:
            prompt = base_prompt + RETRY_NOTE.format(problems="\n".join(f"- {p}" for p in problems))
        try:
            summary, body = parse_response(writer(prompt))
        except ValueError as exc:
            problems = [str(exc)]
        else:
            problems, warnings = check_roundup(summary, body, week_posts, all_posts, rid)
            if not problems:
                return summary, body, warnings, attempt
        print(f"::warning:: {attempt} 回目の下書きは使えませんでした: {problems}", file=sys.stderr)
    raise DraftError(f"{MAX_ATTEMPTS} 回書かせても使える下書きになりませんでした: {problems}")


def build_roundup(rid: str, summary: str, body: str, generated_at: str) -> dict:
    start, end = week_range(rid)
    return {
        "id": rid, "kind": "weekly", "title": weekly_title(rid),
        "period_start": start.isoformat(), "period_end": end.isoformat(),
        "summary": summary, "body": body, "generated_at": generated_at, "model": MODEL,
    }


def render_report(roundup: dict, week_posts: list[dict], warnings: list[str], attempts: int) -> str:
    linked = set(linked_ids(roundup["body"]))
    used = sum(1 for p in week_posts if p["id"] in linked)
    lines = [
        f"## {roundup['title']}",
        "",
        f"> {roundup['summary']}",
        "",
        f"- 本文 {visible_length(roundup['body']):,} 字、対象週の記事 {len(week_posts)} 本中 {used} 本にリンク",
        f"- モデル: {roundup['model']}" + (f"({attempts} 回目の下書き)" if attempts > 1 else ""),
        "",
        "### 機械的な検査",
        "",
        *([f"- [ ] {w}" for w in warnings] or ["機械的な検査で気になる点はありませんでした。"]),
        "",
        "### 公開の手順",
        "",
        "1. Cloudflare Pages のプレビュー(このページの下に付く URL)で `/roundups/` を開いて読む",
        "2. 直す場合は、Files changed からファイルを編集してコミットする",
        "3. 問題なければ Merge する(公開される)。公開しない場合は Close する",
    ]
    return "\n".join(lines) + "\n"


def run(rid: str, all_posts: list[dict], writer: Writer, *, roundups_dir: Path = ROUNDUPS_DIR,
        report_path: Path | None, now: str) -> Path | None:
    """書いたファイル。既にある週・記事のない週は何もしない(None)。"""
    path = roundups_dir / f"{rid}.md"
    if path.exists():
        print(f"{path.name} は既にあるので作りません")
        return None
    week_posts = select_week_posts(all_posts, rid)
    if not week_posts:
        print(f"{rid} の記事がないので作りません")
        return None

    summary, body, warnings, attempts = generate(week_posts, all_posts, rid, writer)
    for w in warnings:
        print(f"::warning:: {w}", file=sys.stderr)
    roundup = build_roundup(rid, summary, body, now)
    roundups_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(to_markdown(roundup), encoding="utf-8", newline="\n")
    if report_path:
        report_path.write_text(render_report(roundup, week_posts, warnings, attempts), encoding="utf-8")
    return path


def report_for_existing(path: Path, all_posts: list[dict]) -> str:
    """既にある下書きを検査し直した結果(PR だけを作り直すとき用)。"""
    roundup = parse_roundup(path)
    week_posts = select_week_posts(all_posts, roundup["id"])
    errors, warnings = check_roundup(roundup["summary"], roundup["body"], week_posts, all_posts, roundup["id"])
    return render_report(roundup, week_posts, errors + warnings, attempts=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", help="対象の週(例: 2026-w44)。省略すると最後に終わった週")
    parser.add_argument("--report", type=Path, help="PR の本文に載せる検査結果を書くファイル")
    parser.add_argument("--print-week", action="store_true", help="対象の週 ID を表示するだけ(API は呼ばない)")
    parser.add_argument("--check", type=Path, metavar="FILE",
                        help="既にある下書きを検査し直し、--report に書く(API は呼ばない)")
    args = parser.parse_args()

    if args.check:
        posts = [parse_post(p) for p in sorted(POSTS_DIR.glob("*.md"))]
        report = report_for_existing(args.check, posts)
        if args.report:
            args.report.write_text(report, encoding="utf-8")
        else:
            print(report)
        return

    now = datetime.now(timezone.utc)
    rid = args.week or default_week(now)
    try:
        week_range(rid)
    except ValueError as exc:
        sys.exit(f"エラー: {exc}")
    if args.print_week:
        print(rid)
        return
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("エラー: OPENAI_API_KEY が設定されていません。")
    posts = [parse_post(p) for p in sorted(POSTS_DIR.glob("*.md"))]
    try:
        path = run(rid, posts, openai_writer(), report_path=args.report,
                   now=now.isoformat(timespec="seconds").replace("+00:00", "Z"))
    except DraftError as exc:
        sys.exit(f"エラー: {exc}")
    if path:
        print(f"下書きを書きました -> {path}")


if __name__ == "__main__":
    main()
