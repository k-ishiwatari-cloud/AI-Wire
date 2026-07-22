# 記事作成用プロンプト(通常のChatGPTにコピペして使う)

Custom GPT / Actionsは使わず、普段の ChatGPT (Web検索が使えるモデル) に
そのまま貼り付けて使うプロンプトです。出力されたMarkdownをそのままローカルに
保存し、`scripts/publish_post.py` で投稿します。

---

## プロンプト本文

```
直近1〜3日以内の、主要なAI関連ニュースを1件選んで、以下の形式のMarkdownで
出力してください。説明や前置きは不要です。コードブロックの中に、この形式
そのままで出力してください。

---
title: "記事タイトル(日本語、40字以内目安)"
date: YYYY-MM-DD
source_name: "情報源の名前(例: OpenAI Blog, TechCrunch, Reuters)"
source_url: "https://情報源への直接リンク"
tags: ["タグ1", "タグ2"]
summary: "2〜3文程度の要約。何が起きたか、なぜ重要かを簡潔に。"
---

(任意) 背景説明や補足コメント。省略可。

条件:
- 一次情報(公式ブログ、プレスリリース、大手報道)を優先し、真偽不明の噂は扱わない
- tagsは Agent, OSS, Framework, Benchmark, Research, Safety, Policy を
  優先して使う。当てはまらない場合のみ新しいタグを追加してよい
- source_url は実在する具体的なURLにすること(架空のURLを作らない)
```

---

## 出力を受け取ったら

1. 出力されたMarkdownをコピー
2. ファイル名を `YYYY-MM-DD-slug.md` の形式で決めて保存
   (slugは英数字とハイフンのみ。例: `2026-07-17-eu-google-ai-competition.md`)
3. ターミナルで投稿:

```bash
python scripts/publish_post.py path/to/2026-07-17-eu-google-ai-competition.md
```

初回のみGitHubのトークン入力を求められます。保存するか聞かれるので、
自分のPCであれば `y` と答えると次回以降は入力不要になります。
