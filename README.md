# AI WIRE — AIニュースフィード

ChatGPTのAIエージェントがAI関連ニュースを収集・要約して投稿し、
Cloudflare Pagesが自動でビルド・配信する静的サイトです。

```
ニュースbot(GitHub Actions) → GitHubに記事(Markdown)をコミット
                             → Cloudflare Pagesがpushを検知して記事一覧・記事ページを静的HTMLとして生成
                             → Cloudflare Pagesで公開(誰でも閲覧可)
```

## ディレクトリ構成

```
ai-news-site/
├── content/
│   └── posts/                      # 1記事1ファイル(Markdown + frontmatter)
│       └── 2026-07-10-xxxx.md
├── scripts/
│   ├── build_manifest.py           # posts/*.md → manifest.json と静的HTML(ビルドコマンド)
│   ├── render_site.py              # 記事一覧・記事ページ・sitemap.xml のHTML生成
│   ├── generate_news.py            # OpenAI APIでニュースを収集し記事を書き出す
│   ├── news_validation.py          # 記事候補の検証(URL到達確認・重複判定)
│   ├── publish_post.py             # ローカルの記事ファイルをGitHubへ直接投稿
│   └── tests/                      # pytest
├── site/                           # Cloudflare Pagesで公開される実体
│   ├── index.html
│   ├── style.css
│   ├── app.js                      # タグ絞り込み・NEW表示(記事の描画はビルド時)
│   ├── _headers                    # レスポンスヘッダ設定(公開はされない)
│   ├── data/manifest.json          # ビルド時に自動生成(手動編集不要)
│   ├── posts/<記事ID>/index.html   # ビルド時に自動生成(git管理外)
│   └── sitemap.xml                 # ビルド時に自動生成(git管理外)
├── aiwire-icons/                   # ロゴ・ファビコンの元データ(公開用は site/ にコピー済み)
├── chatgpt-agent/
│   ├── draft-prompt-template.md    # 通常のChatGPTに貼り付ける記事作成プロンプト
│   ├── openapi-github-actions.yaml # (参考)Custom GPT Actions用スキーマ
│   └── agent-instructions.md       # (参考)Custom GPTのInstructions欄テンプレート
├── .github/workflows/news_bot.yml  # 毎時のニュース自動収集・投稿
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

必須フィールドが欠けているファイルがあると、Cloudflare Pagesのビルドが
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

### 2. Cloudflare Pagesと連携する

1. Cloudflare ダッシュボードで **Workers & Pages > Create > Pages > Connect to Git** を選択
2. GitHub アカウントを連携し、このリポジトリを選択
3. ビルド設定を次のとおり入力する(Framework preset は `None`)

   | 項目 | 値 |
   |---|---|
   | Production branch | `main` |
   | Build command | `pip install pyyaml && python scripts/build_manifest.py` |
   | Build output directory | `site` |

4. **Save and Deploy** を押すと数分で公開される。公開URL(`https://<プロジェクト名>.pages.dev`)は
   プロジェクト画面に表示される

以降は `main` へのpush(ニュースbotの自動投稿を含む)のたびに、Cloudflare Pagesが自動で
再ビルド・公開する。ビルドが失敗した場合は直前の公開状態が維持される。

- 料金: Free プランで運用できる。ビルドは月500回まで(プレビュービルドも含む)。
  ニュースbotのpushは実績で月110回程度だが、毎時新着があると月720回を超えうる。
  上限に達すると新しいビルドができなくなる(サイトの更新が止まる)ので、
  ビルド回数をダッシュボードで時々確認すること。節約したい場合は次の設定が有効:
  - **Settings > Builds > Branch control** でプレビュービルドを無効化
  - **Build watch paths** を `content/posts/*`、`site/*`、`scripts/build_manifest.py`、`scripts/render_site.py` に限定
- ビルド環境: v3 ビルドイメージの Python 3 と pip を使う。バージョンを固定したい場合は
  環境変数 `PYTHON_VERSION` を設定する
- レスポンスヘッダ: `site/_headers` で設定する(`manifest.json` はキャッシュの再利用前に毎回再検証させる)
- 公開範囲: 誰でも閲覧できる。制限したい場合は Cloudflare Access の導入を検討すること

> 旧構成のGitHub Pagesを使っていた場合は、リポジトリの **Settings > Pages** で
> 公開を停止しておくこと(ワークフロー `deploy.yml` は削除済み)。

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

記事はビルド時に HTML として書き出すので、先に手元でビルドしてから確認します。

```bash
pip install pyyaml
python3 scripts/build_manifest.py
```

ビルドは `site/index.html` の `<!-- build:... -->` の目印の間に記事一覧を書き込みます。
手元でビルドすると `site/index.html` に差分が出ますが、コミットしないでください
(`git checkout site/index.html` で元に戻せます。本番では Cloudflare のビルドが毎回書き込みます)。

## 完全自動投稿(news_bot.yml)

ChatGPTへの手動コピペに代わり、OpenAI Responses API + Web検索
(`gpt-5-mini`)を使って1時間ごとに自動でニュースを収集・投稿する
GitHub Actionsワークフローです。

- `scripts/generate_news.py` が直近1〜3日のAIニュースを5〜10件
  Web検索させ、`content/posts/` にMarkdownとして書き出す。日本企業、政府機関・自治体の
  重要なAIニュースも対象とし、該当記事には `Japan` タグを付ける
  (直近14日以内に投稿済みのURLはプロンプトに含めて重複を避ける)
- `.github/workflows/news_bot.yml` が上記スクリプトを毎時5分に実行し、
  新しい記事があればコミット・push する
  (pushを検知してCloudflare Pagesが再ビルドし、サイトへ反映される)
- 記事候補は投稿前に検証する(`scripts/news_validation.py`)。web_searchが実際に
  参照していないURL、到達できないURL、既存記事とタイトルが類似する記事はスキップされる
- サイトの「最終更新」時刻はCloudflare Pagesのビルド時刻。新着記事がない時間帯は進まない
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
