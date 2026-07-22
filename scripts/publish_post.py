#!/usr/bin/env python3
"""ローカルのMarkdown記事ファイルを AI WIRE リポジトリへ直接投稿するスクリプト。

ChatGPT Actionsを介さず、GitHubのContents APIを直接叩く。
使い方:

    python scripts/publish_post.py path/to/2026-07-17-example-slug.md

ファイル名は "YYYY-MM-DD-slug.md" の形式にすること。
そのまま content/posts/ 配下の同名パスとして投稿される。
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

OWNER = "k-ishiwatari-cloud"
REPO = "AI-Wire"
BRANCH = "main"

SCRIPT_DIR = Path(__file__).resolve().parent
TOKEN_CACHE = SCRIPT_DIR / ".github_token"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
REQUIRED_FIELDS = ["title", "date", "source_name", "source_url", "summary"]
FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9\-]+\.md$")


def load_token() -> str:
    env_token = os.environ.get("GITHUB_TOKEN")
    if env_token:
        return env_token

    if TOKEN_CACHE.exists():
        return TOKEN_CACHE.read_text(encoding="utf-8").strip()

    token = getpass.getpass("GitHubのPersonal Access Token(Fine-grained)を入力: ").strip()
    if not token:
        print("トークンが入力されませんでした。", file=sys.stderr)
        sys.exit(1)

    save = input("次回から再入力しなくて済むよう、このPCに保存しますか？ (y/N): ").strip().lower()
    if save == "y":
        TOKEN_CACHE.write_text(token, encoding="utf-8")
        try:
            TOKEN_CACHE.chmod(0o600)
        except OSError:
            pass
        print(f"保存しました: {TOKEN_CACHE}(.gitignoreで除外済み)")

    return token


def validate_local_file(path: Path) -> str:
    if not FILENAME_RE.match(path.name):
        print(
            f"::warning:: ファイル名が 'YYYY-MM-DD-slug.md' 形式ではありません: {path.name}\n"
            "            続行しますが、サイトの日付ソートに影響する可能性があります。",
            file=sys.stderr,
        )

    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        print(f"エラー: frontmatter(--- で囲まれたメタ情報)が見つかりません: {path}", file=sys.stderr)
        sys.exit(1)

    front_raw, _ = match.groups()
    meta = yaml.safe_load(front_raw) or {}
    missing = [key for key in REQUIRED_FIELDS if key not in meta or meta[key] in (None, "")]
    if missing:
        print(f"エラー: 必須フィールドが不足しています -> {missing}", file=sys.stderr)
        sys.exit(1)

    print(f"確認OK: 「{meta['title']}」({meta['date']}) を投稿します。")
    return text


def publish(path: Path, text: str, token: str) -> None:
    remote_path = f"content/posts/{path.name}"
    content_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")

    payload = {
        "message": f"add: {path.stem}",
        "content": content_b64,
        "branch": BRANCH,
    }

    req = urllib.request.Request(
        f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{remote_path}",
        data=json.dumps(payload).encode("utf-8"),
        method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            html_url = data.get("content", {}).get("html_url", "")
            print(f"投稿成功 ({resp.status})")
            print(f"-> {html_url}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        print(f"投稿失敗 (HTTP {exc.code})", file=sys.stderr)
        print(detail, file=sys.stderr)
        if exc.code in (409, 422):
            print(
                "\nヒント: 同名ファイルが既に存在する可能性があります。"
                "ファイル名(日付やslug)を変えてもう一度試してください。",
                file=sys.stderr,
            )
        elif exc.code == 401:
            print("\nヒント: トークンが無効か期限切れです。再発行してください。", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        print("使い方: python scripts/publish_post.py path/to/記事.md", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1]).expanduser().resolve()
    if not path.exists():
        print(f"ファイルが見つかりません: {path}", file=sys.stderr)
        sys.exit(1)

    text = validate_local_file(path)
    token = load_token()
    publish(path, text, token)


if __name__ == "__main__":
    main()
