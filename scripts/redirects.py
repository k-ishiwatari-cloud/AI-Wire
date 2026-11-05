"""site/_redirects(Cloudflare Pages の転送設定)の読み書き。

書式は 1 行に「転送元 転送先 [ステータス]」。# で始まる行と空行は無視される。
https://developers.cloudflare.com/pages/configuration/redirects/
"""
from __future__ import annotations

import re
from pathlib import Path

REDIRECTS_PATH = Path(__file__).resolve().parent.parent / "site" / "_redirects"
_POST_PATH_RE = re.compile(r"^/posts/([^/]+)/?$")


def parse_rule(line: str) -> tuple[str, str, str | None] | None:
    """(転送元, 転送先, ステータス)。ルールでない行(コメント・空行・書式違い)は None。"""
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    parts = line.split()
    if len(parts) == 2:
        return parts[0], parts[1], None
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return None


def post_id_of(path: str) -> str | None:
    """/posts/<ID>/ または /posts/<ID> なら ID。記事ページ以外は None。"""
    match = _POST_PATH_RE.match(path)
    return match.group(1) if match else None


def redirected_post_ids(redirects_path: Path = REDIRECTS_PATH) -> set[str]:
    """転送元になっている記事 ID。この ID で記事を書くと転送に隠されるので、新しい記事には使わない。"""
    if not redirects_path.exists():
        return set()
    rules = (parse_rule(line) for line in redirects_path.read_text(encoding="utf-8").splitlines())
    return {post_id_of(rule[0]) for rule in rules if rule and post_id_of(rule[0])}
