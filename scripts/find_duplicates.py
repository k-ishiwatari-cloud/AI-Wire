#!/usr/bin/env python3
"""content/posts/ の中から同じニュースを扱う記事の組を探し、1 本に統合する。

判定は投稿時の重複チェック(news_validation.py)と同じタイトル類似度と、出典 URL の一致による。
似ているだけで別のニュースのこともあり、閾値では分けられない(本当の重複と別ニュースの類似度が重なる)。
そのため、まずレポートを出して人が確認し、別ニュースの記事を --exclude で外してから統合する。
確認した内容と統合する内容がずれないよう(確認中に bot の投稿が増えると組み合わせが変わりうる)、
レポートと同時に計画ファイルを書き出し、統合はその計画どおりに行う。

使い方:
    python scripts/find_duplicates.py --plan plan.json                  # レポートを標準出力へ、計画をファイルへ
    python scripts/find_duplicates.py --exclude a,b --plan plan.json    # 記事 a, b を候補から外して作り直す
    python scripts/find_duplicates.py --apply plan.json                 # 確認した計画どおりに統合する

統合では、残す記事以外を削除し、消した記事の URL を site/_redirects で残す記事へ 301 転送する。
インデックス済みの URL を 404 にしないため。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

from build_manifest import POSTS_DIR, parse_post
from news_validation import TITLE_SIMILARITY_THRESHOLD, _cosine, _idf, normalize_url
from redirects import REDIRECTS_PATH, parse_rule, post_id_of
from render_site import POST_ID_RE

Plan = list[tuple[str, list[str]]]  # (残す記事 ID, 削除する記事 ID)
WINDOW_DAYS = 14  # 投稿時の重複チェックが既存記事をさかのぼる日数(generate_news.LOOKBACK_DAYS)と同じ


def _days_apart(a: dict, b: dict) -> int:
    return abs((date.fromisoformat(a["date"]) - date.fromisoformat(b["date"])).days)


def _keep_order(post: dict):
    """残す記事ほど小さい。本文あり → 先に投稿された記事 → 日付が早い記事 → ID の順。"""
    return (not post["body"], post["posted_at"] is None, post["posted_at"] or "", post["date"], post["id"])


def find_duplicate_groups(
    posts: list[dict],
    corpus: list[str] | None = None,
    threshold: float = TITLE_SIMILARITY_THRESHOLD,
    window_days: int = WINDOW_DAYS,
    exclude: set[str] = frozenset(),
) -> list[list[dict]]:
    """重複する記事の組。各組の先頭が残す記事。corpus はタイトル類似度の重み付けに使う(既定は posts のタイトル)。

    exclude の記事は候補から外す。外しても重み付けは変わらないよう、類似度は posts 全体で計算する。
    """
    idf = _idf([*(corpus or []), *(p["title"] for p in posts)])
    posts = [p for p in posts if p["id"] not in exclude]
    urls = [normalize_url(p["source_url"]) for p in posts]

    parent = list(range(len(posts)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(posts):
        for j in range(i + 1, len(posts)):
            b = posts[j]
            if _days_apart(a, b) > window_days:
                continue
            if urls[i] == urls[j] or _cosine(a["title"], b["title"], idf) >= threshold:
                parent[root(j)] = root(i)

    groups: dict[int, list[dict]] = {}
    for i, post in enumerate(posts):
        groups.setdefault(root(i), []).append(post)
    result = [sorted(g, key=_keep_order) for g in groups.values() if len(g) > 1]
    return sorted(result, key=lambda g: (g[0]["date"], g[0]["id"]))


def render_report(groups: list[list[dict]]) -> str:
    lines = [f"# 重複候補 {len(groups)} 組(削除候補 {sum(len(g) - 1 for g in groups)} 件)", ""]
    for n, group in enumerate(groups, start=1):
        lines.append(f"## {n}. {group[0]['title']}")
        for i, post in enumerate(group):
            mark = "**残す**" if i == 0 else "削除"
            body = " 本文あり" if post["body"] else ""
            lines.append(f"- {mark} `{post['id']}` {post['date']} {post['title']}{body}")
            lines.append(f"  - {post['source_url']}")
        lines.append("")
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def to_plan(groups: list[list[dict]], posts_dir: Path) -> dict:
    """確認時点の記事の中身(ハッシュ)も記録し、確認後に書き換えられた記事を消さないようにする。"""
    return {
        "groups": [{"keep": g[0]["id"], "remove": [p["id"] for p in g[1:]]} for g in groups],
        "sha256": {p["id"]: _sha256(posts_dir / f"{p['id']}.md") for g in groups for p in g},
    }


def load_plan(path: Path) -> tuple[Plan, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if any(not isinstance(g["remove"], list) for g in data["groups"]):
        raise ValueError("remove は記事 ID の配列で指定してください")
    plan = [(g["keep"], g["remove"]) for g in data["groups"]]
    hashes = data.get("sha256", {})
    keeps = [keep for keep, _ in plan]
    removes = [r for _, remove in plan for r in remove]
    # 計画ファイルは手で編集されうるので、content/posts/ の外を指す ID を受け付けない
    bad = [id_ for id_ in [*keeps, *removes] if not isinstance(id_, str) or not POST_ID_RE.fullmatch(id_)]
    if bad:
        raise ValueError(f"記事 ID として不正な値があります: {bad}")
    if set(keeps) | set(removes) != set(hashes):
        raise ValueError("計画の記事とハッシュの記録が一致しません")
    if any(not remove for _, remove in plan):
        raise ValueError("削除する記事がない組があります")
    if len(set(removes)) != len(removes):
        raise ValueError("同じ記事が複数の組で削除対象になっています")
    if set(keeps) & set(removes):
        raise ValueError(f"残す記事が削除対象にも入っています: {sorted(set(keeps) & set(removes))}")
    return plan, hashes


def _redirect_lines(src_id: str, dst_id: str) -> list[str]:
    # 末尾のスラッシュの有無どちらで来ても転送する
    return [f"/posts/{src_id}/ /posts/{dst_id}/ 301", f"/posts/{src_id} /posts/{dst_id}/ 301"]


def _merged_redirects(lines: list[str], kept_for: dict[str, str]) -> list[str]:
    result = []
    for line in lines:
        rule = parse_rule(line)
        if rule and post_id_of(rule[1]) in kept_for:
            src, dst, status = rule
            line = " ".join(filter(None, [src, f"/posts/{kept_for[post_id_of(dst)]}/", status]))
        result.append(line)
    for src_id, dst_id in kept_for.items():
        result += [line for line in _redirect_lines(src_id, dst_id) if line not in result]
    return result


def apply_merge(
    plan: Plan, hashes: dict[str, str] | None = None, *, posts_dir: Path, redirects_path: Path
) -> None:
    """転送の追加と記事の削除をまとめて行う。途中で失敗したら両方とも元に戻す。

    hashes(計画を作った時点の記事のハッシュ)を渡すと、それ以降に書き換えられた記事があれば何もせず中止する。
    """
    kept_for = {r: keep for keep, remove in plan for r in remove}
    paths = {id_: posts_dir / f"{id_}.md" for id_ in [*(k for k, _ in plan), *kept_for]}
    missing = [p.name for p in paths.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(f"記事が見つかりません(計画を作り直してください): {missing}")
    if hashes is not None:
        changed = [p.name for id_, p in paths.items() if _sha256(p) != hashes[id_]]
        if changed:
            raise ValueError(f"計画を作った後に書き換えられた記事があります(計画を作り直してください): {changed}")

    old_redirects = redirects_path.read_text(encoding="utf-8") if redirects_path.exists() else None
    new_redirects = "\n".join(_merged_redirects((old_redirects or "").splitlines(), kept_for)) + "\n"
    backups = {id_: paths[id_].read_bytes() for id_ in kept_for}

    tmp = redirects_path.with_name(redirects_path.name + ".tmp")
    tmp.write_text(new_redirects, encoding="utf-8")
    os.replace(tmp, redirects_path)
    deleted: list[str] = []
    try:
        for id_ in kept_for:
            paths[id_].unlink()
            deleted.append(id_)
    except BaseException:
        _roll_back(deleted, backups, paths, redirects_path, old_redirects)
        raise


def _roll_back(deleted, backups, paths, redirects_path: Path, old_redirects: str | None) -> None:
    """消した記事だけを書き戻し、転送を元に戻す。1 つ失敗しても残りの復元は続け、失敗した対象を知らせる。"""
    failed = []
    for id_ in deleted:
        try:
            paths[id_].write_bytes(backups[id_])
        except OSError:
            failed.append(paths[id_].name)
    try:
        if old_redirects is None:
            redirects_path.unlink()
        else:
            redirects_path.write_text(old_redirects, encoding="utf-8")
    except OSError:
        failed.append(redirects_path.name)
    if failed:
        print(f"::error:: 元に戻せなかったファイルがあります(git checkout で復元してください): {failed}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exclude", default="", help="重複ではないと確認した記事 ID(カンマ区切り)")
    parser.add_argument("--plan", type=Path, help="統合の計画を書き出すファイル")
    parser.add_argument("--apply", type=Path, metavar="PLAN", help="確認した計画どおりに統合する")
    args = parser.parse_args()

    if args.apply:
        plan, hashes = load_plan(args.apply)
        apply_merge(plan, hashes, posts_dir=POSTS_DIR, redirects_path=REDIRECTS_PATH)
        print(f"{sum(len(r) for _, r in plan)} 件を削除し、{REDIRECTS_PATH} に転送を追加しました")
        return

    posts = [parse_post(p) for p in sorted(POSTS_DIR.glob("*.md"))]
    excluded = {s.strip() for s in args.exclude.split(",") if s.strip()}
    unknown = excluded - {p["id"] for p in posts}
    if unknown:
        sys.exit(f"存在しない記事 ID です: {sorted(unknown)}")
    groups = find_duplicate_groups(posts, exclude=excluded)
    if args.plan:
        args.plan.write_text(json.dumps(to_plan(groups, POSTS_DIR), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(render_report(groups))


if __name__ == "__main__":
    main()
