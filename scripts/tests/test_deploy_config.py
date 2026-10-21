"""Cloudflare Pages での公開設定が、リポジトリ構成と食い違っていないことを確認する。

実環境でのビルド・配信の動作保証ではない。

ビルドコマンドと公開ディレクトリは Cloudflare のダッシュボードで設定する(README 参照)。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"

BUILD_COMMAND = "pip install pyyaml && python scripts/build_manifest.py"


def _header_rules() -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    current = None
    for line in (SITE / "_headers").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            rules[current].append(line.strip())
        else:
            current = line.strip()
            rules[current] = []
    return rules


def test_site_dir_contains_entrypoints():
    for name in ("index.html", "app.js", "style.css"):
        assert (SITE / name).is_file(), name


def test_build_generates_manifest_from_posts(tmp_path, monkeypatch):
    """ビルドコマンドが実行する build_manifest.py で、全記事を含む manifest.json が生成できる。"""
    import json

    import build_manifest

    output = tmp_path / "data" / "manifest.json"
    monkeypatch.setattr(build_manifest, "OUTPUT_PATH", output)
    build_manifest.main()

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["posts"]) == len(list((ROOT / "content" / "posts").glob("*.md")))
    assert all(p["title"] and p["source_url"] for p in payload["posts"])


def test_readme_documents_cloudflare_build_settings():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Cloudflare Pages" in readme
    assert BUILD_COMMAND in readme
    assert "`site`" in readme


def test_manifest_requires_revalidation():
    """新着記事がすぐ反映されるよう、manifest.json はキャッシュ再利用前に再検証を要求する。"""
    values = _header_rules()["/data/manifest.json"]
    assert any(v.startswith("Cache-Control:") and "no-cache" in v for v in values)


def test_previous_hosting_configs_are_removed():
    assert not (ROOT / ".github" / "workflows" / "deploy.yml").exists()
    assert not (ROOT / "netlify.toml").exists()
