# AI-Wire セッション引き継ぎメモ (Claude Code → Codex)

対象リポジトリ: `k-ishiwatari-cloud/AI-Wire`(GitHub, public)
ローカルパス: `C:\Users\k-ishiwatari\Documents\AI-Wire`
作成日: 2026-09-09

## プロジェクト概要

AIに関する最新ニュースを自動収集し、GitHub Pagesで配信する個人メディアサイト。

- `scripts/generate_news.py` — OpenAI Responses API (`web_search`ツール付き)で直近のAI関連ニュースを検索・要約し、`content/posts/*.md`にfrontmatter付きMarkdownとして書き出す。GitHub Actionsから定期実行される想定で、コミット・pushはワークフロー側が担当し、このスクリプト自身はローカルにファイルを書き出すところまで。
- `scripts/build_manifest.py` — `content/posts/`から`site/data/manifest.json`を生成(デプロイ時にビルドされるだけで、生成物はリポジトリにコミットされない)。
- `site/` — ビルドステップ不要の素のHTML/CSS/JS。`site/app.js`がmanifest.jsonを読み込みフィード表示・タグフィルタを描画する。
- `.github/workflows/news_bot.yml` — 毎時5分に`generate_news.py`を実行し、新着があればcommit・push。
- `.github/workflows/deploy.yml` — `content/posts/**`等の変更push、または毎時20分の定期実行でGitHub Pagesへデプロイ(「最終更新」時刻を進める目的で新着有無に関わらず動く)。

## このセッションで行った作業(時系列)

1. **news_bot.yml の実行失敗を調査・修正**
   - GitHub Actions上で `generate` ジョブが exit code 1 で失敗しているという報告から着手。
   - `gh` CLIが未インストール、かつユーザーもインストールしていなかったため、GitHub REST APIを認証なしで直接叩いて調査(このリポジトリはpublicなので `api.github.com/repos/.../actions/runs` 等は認証不要で読める。ただしジョブの生ログダウンロード(`.../jobs/{id}/logs`)は"Must have admin rights"で拒否されるため、ユーザーにActions画面から該当ステップの「Copy log」で貼ってもらって特定した)。
   - 根本原因: `resp = client.responses.create(model="gpt-5-mini", tools=[{"type":"web_search"}], max_output_tokens=8000)` において、`gpt-5-mini`(推論モデル)がreasoning+web_search呼び出しでトークンを消費し尽くし、最終テキスト出力前に打ち切られ `resp.output_text` が空になっていた。
   - 修正 (`scripts/generate_news.py`, commit `63524da`): `reasoning={"effort": "low"}` を追加、`max_output_tokens` を8000→32000に増量、空応答時のエラーメッセージに `status`/`incomplete_reason` を出力するよう改善。
   - 9/3〜9/7の自動実行で正常動作していることを確認済み。

2. **検索範囲の調整** (commit `3578cf8`)
   - ユーザー要望「なるべく近い時間のニュースを拾いたい」を受け、プロンプト冒頭の「直近1〜3日以内」を「直近0〜2日以内」に変更(`PROMPT_TEMPLATE`内の一文のみ)。
   - `LOOKBACK_DAYS = 14`(重複除外用の既出チェック期間)は変更していない。

3. **Chinaタグ機能の追加 → 撤回**
   - 追加 (commit `447322e`): `PREFERRED_TAGS`に`"China"`追加、プロンプト条件に「中国発ニュースも積極的に検索対象へ」「中国主体のニュースには必ずChinaタグ併用」を追記、`site/app.js`の`TAG_ORDER`にもChinaを追加。
   - この機能追加により9/4・9/7・9/8にTencent/Alibaba/Baidu/中国外交部関連の記事11件が生成された。
   - 直後にユーザーが方針転換し撤回を依頼:「やっぱり中国発のAIニュースは検索対象から外してください。またChinaタグが付いている投稿を削除してください」
   - 撤回 (commit `c8e9a1c`): `git revert --no-commit 447322e` でコード側を完全に元に戻し、frontmatterの`tags`に`China`を含む投稿11件を`git rm`。1コミットにまとめてpush。
   - 現状、`scripts/generate_news.py`・`site/app.js`は中国機能追加前と同一内容、`content/posts/`にChinaタグの投稿は残っていない。

## 運用上の既知事項・詰まりどころ

- **`gh` CLI は未インストール**。ローカルではPowerShell/Bashどちらからも `gh` コマンドは使えない。Actions関連の調査は `curl` + `api.github.com` の素のREST APIで行う(publicリポジトリなので認証不要な範囲が広いが、ジョブの生ログ本文だけは認証必須で取得不可。annotationsやrun/jobsのメタ情報は取れる)。
- **codex CLIがspend cap(利用上限)エラーで動作不能な状態が続いている**。このセッション中、コードレビューを試みる度に以下のエラーで失敗している:
  ```
  ERROR: You hit your spend cap set by the owner of your workspace. Ask an owner to increase your spend cap to continue.
  ```
  codex.exeのパスは固定でなく毎回 `find "$LOCALAPPDATA/OpenAI/Codex/bin" -name codex.exe` で探す必要がある(更新のたびにハッシュ付きディレクトリが変わる)。ワークスペースのオーナーに上限緩和を依頼する必要がある。
- **git commit時に author情報の警告が出る**(`石渡 夏駒 <k-ishiwatari@sbpl.local>` が自動設定されたものである旨のGit警告)。動作に支障はないが、必要なら `git config --global user.name/user.email` を設定した方がよい。
- コミットのpush前には毎回 `git fetch && git log --oneline main..origin/main` でnews_botの自動コミット(`news: automated post YYYY-MM-DD`)が積まれていないか確認し、必要ならrebaseしてからpushする運用にしていた(自動投稿が毎時走るため、リモートが頻繁に進む)。

## CLAUDE.md の適用ルール(このリポジトリ/環境で有効な開発方針)

`C:\Users\k-ishiwatari\Documents\CLAUDE.md` にプロジェクト横断の指示があり、このセッションでも順守していた。主要点:

- TDDで開発(探索→Red→Green→Refactoring)。不明瞭な指示は質問して明確化する。
- 関心の分離、状態とロジックの分離、可読性・保守性重視。静的検査可能なルールはlinter/ast-grepで書く。
- **公開リポジトリではドキュメント・コミットメッセージは英語**、それ以外(社内・プライベート)は日本語(`feat:`/`fix:`等のprefixは英語のままでよい)。ただしこのセッションでは実際には日本語でコミットメッセージを書いていた(AI-Wireがpublicリポジトリであることを踏まえると、本来は英語で書くべきだった可能性がある点、要注意)。
- コマンド・ブラウザ操作はヘッドレス・サイレント優先。GUI操作は明示要求時のみ。
- **コード・instructionの差分はユーザー提示前に必ずcodexでレビューを通す**運用だが、前述の通りspend capで実行不能な状態が続いており、ユーザーの了承を得た上でレビュー省略のまま提示・コミットしていた回が複数ある。codexが復旧したら、このセッションでの変更(特に3578cf8, 447322e, c8e9a1c)を事後的にレビューしておくとよい。
- エージェント運用ルール(メインセッションがFableのときサブエージェントに委譲する等)はメインセッションのモデルがSonnet 5だったため今回は不適用。

## 引き継ぎ時の注意

- 直近のリポジトリ状態は `c8e9a1c`(2026-09-09)。ユーザーは中国ニュース機能を明確に「やっぱりやめる」と撤回した経緯があるため、今後同様の提案をする場合はこの経緯を踏まえること。
- news_bot.ymlは1時間ごとに自動実行され続けているため、作業前に必ず最新の`origin/main`を取り込むこと。
