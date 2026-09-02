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
│   ├── build_manifest.py           # posts/*.md → site/data/manifest.json
│   └── publish_post.py             # ローカルの記事ファイルをGitHubへ直接投稿
├── site/                           # GitHub Pagesとして公開される実体
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── data/manifest.json          # ビルド時に自動生成(手動編集不要)
├── chatgpt-agent/
│   ├── draft-prompt-template.md    # 通常のChatGPTに貼り付ける記事作成プロンプト
│   ├── openapi-github-actions.yaml # (参考)Custom GPT Actions用スキーマ
│   └── agent-instructions.md       # (参考)Custom GPTのInstructions欄テンプレート
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

### 3. 記事を投稿する(ChatGPT + 手動スクリプト方式)

Custom GPT Actionsは、モデルがAction呼び出し自体を実行せず説明で
終わらせてしまう挙動が確認されたため(2026年7月時点、OpenAIコミュニティ
フォーラムでも同様の報告あり)、現在は以下の**確実に動く方式**を採用して
います。

1. `chatgpt-agent/draft-prompt-template.md` 内のプロンプトを、通常の
   ChatGPT(Web検索が使えるモデル)にそのまま貼り付ける
2. 出力されたMarkdownを `YYYY-MM-DD-slug.md` という名前でローカルに保存
3. 投稿スクリプトを実行

```bash
python scripts/publish_post.py path/to/2026-07-17-example-slug.md
```

初回はGitHubの **Fine-grained Personal Access Token**(対象リポジトリ
限定、`Contents: Read and write` のみ)の入力を求められます。保存するか
聞かれた場合 `y` と答えると、次回以降は入力不要になります(トークンは
`scripts/.github_token` に保存され、`.gitignore` で除外済み)。

frontmatterの必須フィールドが欠けている場合は、投稿前にスクリプト側で
エラーになり弾かれます。

#### (参考)Custom GPT Actionsによる完全自動化について

`chatgpt-agent/openapi-github-actions.yaml` と `agent-instructions.md` は
Custom GPT Actionsでの完全自動投稿を試みた際の設定一式として残して
あります。GitHub API側の疎通・認証(PAT)は問題なく動作することを
確認済みなので、今後ChatGPT側の挙動が改善された場合や、モデルの
選択(Instant系など)・`x-openai-isConsequential: false` の指定などを
工夫することで動く可能性はあります。試す場合はこれらのファイルを
参照してください。

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

## 完全自動投稿(news_bot.yml)

ChatGPTへの手動コピペに代わり、OpenAI Responses API + Web検索
(`gpt-5-mini`)を使って毎朝(07:00 JST)自動でニュースを収集・投稿する
GitHub Actionsワークフローです。

- `scripts/generate_news.py` が直近1〜3日のAIニュースを5〜10件
  Web検索させ、`content/posts/` にMarkdownとして書き出す
  (直近14日以内に投稿済みのURLはプロンプトに含めて重複を避ける)
- `.github/workflows/news_bot.yml` が上記スクリプトを毎朝実行し、
  生成されたファイルをそのままコミット・push する
  (push契機で既存の `deploy.yml` が起動し、サイトへ反映される)
- 手動実行も可能(Actionsタブから `workflow_dispatch`)

### セットアップ

リポジトリの **Settings > Secrets and variables > Actions** で
`OPENAI_API_KEY` を登録してください。

### 既知の注意点

- Web検索を使っていても、AIが日付や固有名詞を誤る可能性はゼロではない
  (ハルシネーション)。定期的に生成内容を確認することを推奨
- `chatgpt-agent/` 配下の手動コピペ方式は、自動化が動かない場合の
  フォールバックとして残してある

## 今後の拡張案(検討中)

- 投稿を即時反映せず、Pull Requestを作らせてレビューを挟む運用
- タグの自動正規化(表記ゆれの吸収)
- 全文検索・週次サマリーページ
- Slack通知連携(新着記事をチャンネルに自動投稿)
