---
title: Cloudflare、GLM‑5.3での応答露出を報告
date: '2026-10-26'
source_name: Cloudflare
source_url: https://blog.cloudflare.com/kv-cache-exposure-remediation/
tags:
- Safety
- OSS
- Other
summary: CloudflareはWorkers AI上で提供していたGLM‑5.3モデルにおいて、KVキャッシュに起因するクロスリクエストのデータ露出が発生し155件の応答が他ユーザーのデータを含んだと公表した。問題はSGLangエンジンとデプロイ設定の組合せにあり、既に修正と調整を実施済み。マルチテナント環境での推論エンジン運用の注意点を示す事例だ。
posted_at: '2026-10-28T20:57:27.572363Z'
---

