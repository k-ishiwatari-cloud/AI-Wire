"""まとめ記事(content/roundups/*.md)のファイル形式と、対象期間の決め方。

ファイル名(拡張子なし)がまとめの ID で、URL は /roundups/<ID>/ になる。
週次まとめの ID は ISO 週番号(例: 2026-w44 = 2026-10-26(月)〜11-01(日))。

    ---
    kind: weekly
    title: 週次まとめ 2026年10月26日〜11月1日
    period_start: '2026-10-26'
    period_end: '2026-11-01'
    summary: 一覧と <meta description> に出す要約
    generated_at: '2026-11-01T22:05:00Z'
    model: gpt-5.6-luna
    ---
    本文(roundup_markdown.py が扱える Markdown)
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import yaml

from render_site import POST_ID_RE

ROUNDUPS_DIR = Path(__file__).resolve().parent.parent / "content" / "roundups"
KINDS = {"weekly"}
FIELDS = ["kind", "title", "period_start", "period_end", "summary", "generated_at", "model"]

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_WEEK_ID_RE = re.compile(r"^(\d{4})-w(\d{2})$")


# ---- 週 ----

def week_id(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-w{week:02d}"


def week_range(rid: str) -> tuple[date, date]:
    """(月曜, 日曜)。"""
    match = _WEEK_ID_RE.match(rid)
    if not match:
        raise ValueError(f"週次まとめの ID は 2026-w44 の形で指定してください: {rid}")
    monday = date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
    return monday, monday + timedelta(days=6)


def previous_week(today: date) -> str:
    """today の時点で最後に終わった週。"""
    return week_id(today - timedelta(days=today.isoweekday()))


def _jp_date(d: date, with_year: bool = True) -> str:
    return f"{d.year}年{d.month}月{d.day}日" if with_year else f"{d.month}月{d.day}日"


def weekly_title(rid: str) -> str:
    start, end = week_range(rid)
    return f"週次まとめ {_jp_date(start)}〜{_jp_date(end, with_year=end.year != start.year)}"


# ---- ファイル ----

def to_markdown(roundup: dict) -> str:
    front = {key: roundup[key] for key in FIELDS}
    yaml_text = yaml.safe_dump(front, allow_unicode=True, sort_keys=False, width=10_000)
    return f"---\n{yaml_text}---\n{roundup['body'].strip()}\n"


def parse_roundup(path: Path) -> dict:
    rid = path.stem
    if not POST_ID_RE.fullmatch(rid):
        raise ValueError(f"URL に使えないまとめ ID です: {path.name}")
    match = _FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"frontmatter (--- で囲まれたメタ情報) が見つかりません: {path.name}")
    front_raw, body = match.groups()
    meta = yaml.safe_load(front_raw) or {}
    if not isinstance(meta, dict):
        raise ValueError(f"{path.name}: frontmatter は「名前: 値」の形で書いてください")
    missing = [key for key in FIELDS if meta.get(key) in (None, "")]
    if missing:
        raise ValueError(f"{path.name}: 必須フィールドが不足しています -> {missing}")
    if meta["kind"] not in KINDS:
        raise ValueError(f"{path.name}: kind は {sorted(KINDS)} のいずれかです: {meta['kind']}")
    roundup = {"id": rid, **{key: str(meta[key]) for key in FIELDS}, "body": body.strip()}
    if not roundup["body"]:
        raise ValueError(f"{path.name}: 本文が空です")
    _check_period(path.name, roundup)
    return roundup


def _check_period(name: str, roundup: dict) -> None:
    """人が PR 上で編集することもあるので、読み込むたびに週 ID と期間が合っているか確かめる。"""
    try:
        period = date.fromisoformat(roundup["period_start"]), date.fromisoformat(roundup["period_end"])
    except ValueError as exc:
        raise ValueError(f"{name}: period_start / period_end を日付として読めません") from exc
    try:
        expected = week_range(roundup["id"])
    except ValueError as exc:
        raise ValueError(f"{name}: 週次まとめのファイル名は 2026-w44.md の形にしてください") from exc
    if period != expected:
        raise ValueError(f"{name}: 期間が週 ID と合いません(正しくは {expected[0]}〜{expected[1]})")


def load_roundups(roundups_dir: Path = ROUNDUPS_DIR) -> list[dict]:
    """新しい期間が先。"""
    if not roundups_dir.exists():
        return []
    items = [parse_roundup(p) for p in sorted(roundups_dir.glob("*.md"))]
    return sorted(items, key=lambda r: (r["period_start"], r["id"]), reverse=True)
