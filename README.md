# AI WIRE — 社内向けAIニュースフィード

ChatGPTのAIエージェントがAI関連ニュースを収集・要約して投稿し、
GitHub Actionsが自動でビルド・配信する社内向け静的サイトです。

```
ChatGPTエージェント → GitHubに記事(Markdown)をコミット
                        → GitHub Actionsがmanifest.jsonを生成
                        → GitHub Pagesへ自動デプロイ → 社内公開
```

## ディレクトリ構成

```
ai-news-site/
├── content/
│   └── posts/                      # 1記事1ファイル(Markdown + frontmatter)
│       └── 2026-07-10-xxxx.md
├── scripts/
│   └── build_manifest.py           # posts/*.md → site/data/manifest.json
├── site/                           # GitHub Pagesとして公開される実体
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── data/manifest.json          # ビルド時に自動生成(手動編集不要)
├── chatgpt-agent/
│   ├── openapi-github-actions.yaml # Custom GPT Actions用スキーマ
│   └── agent-instructions.md       # Custom GPTのInstructions欄テンプレート
├── .github/workflows/deploy.yml    # push契機で自動ビルド・デプロイ
└── README.md
```

## 記事フォーマット

`content/posts/YYYY-MM-DD-slug.md` という名前でファイルを作成します。

```markdown
---
title: "記事タイトル"
date: 2026-07-10
source_name: "情報源の名前"
source_url: "https://example.com/article"
tags: ["Agent", "OSS"]
summary: "2〜3文の要約。"
---

任意の本文(補足コメントなど、省略可)
```

必須フィールドが欠けているファイルがあると、GitHub Actionsのビルドが
失敗するようにしてあります(サイトが壊れた状態で公開されるのを防ぐため)。

## セットアップ手順

### 1. リポジトリを作成

会社のGitHub Organization配下に **Private** リポジトリとして作成し、
このディレクトリの中身をそのままpushしてください。

```bash
cd ai-news-site
git init
git add .
git commit -m "init: AI WIRE scaffold"
git branch -M main
git remote add origin https://github.com/<org>/<repo>.git
git push -u origin main
```

### 2. GitHub Pagesを有効化

リポジトリの **Settings > Pages** で:

- **Source**: `GitHub Actions` を選択
- **Visibility**(GitHub Enterprise Cloudの場合のみ表示):
  `Private` を選択 → Organizationメンバーのみ閲覧可能になります

> Enterprise Cloud以外のプランでは、Pagesのprivate公開自体ができません。
> その場合はNetlify/Vercel等 + Basic認証、または社内サーバーへの
> 静的ファイル配置に切り替える必要があります。

設定後、`main` にpushすると `.github/workflows/deploy.yml` が動作し、
数分でサイトが公開されます。公開URLはリポジトリの Pages 設定画面、
またはActionsの実行ログに表示されます。

### 3. ChatGPTエージェントと連携する

1. ChatGPTで **Explore GPTs > Create** からCustom GPTを新規作成
2. `chatgpt-agent/agent-instructions.md` の内容をInstructions欄に貼り付け、
   Organization名などを実際の値に置き換える
3. Actionsに `chatgpt-agent/openapi-github-actions.yaml` を登録
4. GitHubで **Fine-grained Personal Access Token** を発行
   - 対象リポジトリをこのリポジトリのみに限定
   - 権限は `Contents: Read and write` のみ
5. Custom GPTのAuthenticationに、発行したPATをBearer Tokenとして設定

これで、エージェントに「今日のAIニュースを投稿して」と依頼すると、
GitHub API経由で `content/posts/` に記事ファイルが追加され、
自動的にサイトへ反映されます。

### 4. ローカルでプレビュー

```bash
cd site
python3 -m http.server 8000
# http://localhost:8000 を開く
```

記事を追加した場合は、先に手元でmanifestを再生成してから確認します。

```bash
pip install pyyaml
python3 scripts/build_manifest.py
```

## 今後の拡張案(検討中)

- 投稿を即時反映せず、Pull Requestを作らせてレビューを挟む運用
- タグの自動正規化(表記ゆれの吸収)
- 全文検索・週次サマリーページ
- Slack通知連携(新着記事をチャンネルに自動投稿)
