# [analysis] 取得バックエンドの信頼性

## 目的
fxtwitter / vxtwitter / syndication の欠損率・レート制限・数値ズレを測る。

## 検証方法
同一ポスト100件を3バックエンドで取得し、likes/replies の一致率、
views 欠損率、失敗率を記録。フォールバック順を最適化する。

## 実装
`scripts/audit_backends.py` でURL/IDを標準入力または引数から受け取り、
成功率、レイテンシ、フィールド取得率、バックエンド間の相対差をJSON化する。

## 完了条件
- [x] 100件以上かつ投稿時刻・メディア種別を分散した標本を固定する
- [x] 本文・著者・URL・credentialを除外したsnapshot receiptを実装する
- [x] 同一cohort・3 snapshot・3 UTC時間帯を検証する集約CLIを実装する
- [x] 異なる時間帯に3回以上測定する（3/3）
- [x] 結果に基づき `BACKENDS` の順序またはタイムアウトを更新する

## 2026-07-30 進捗

120件cohortを異なる3 UTC時間帯で正式測定した。

| backend | 成功率 | median | p95 | views |
|---|---:|---:|---:|---:|
| FxTwitter | 321/360 (89.2%) | 355 ms | 458 ms | 321/360 |
| VxTwitter | 321/360 (89.2%) | 81 ms | 203 ms | 0/360 |
| Syndication | 318/360 (88.3%) | 339 ms | 659 ms | 0/360 |

SyndicationのHTTP 200 tombstoneを成功扱いする不具合を発見し、要求した`id_str`との一致を
必須にした。修正版では14 tombstoneを失敗として計上する。

cohortは観測可能107件中video 21 / non-video 86、投稿日6日。3回とも集約順は
`FxTwitter → VxTwitter → Syndication`で、views/bookmarksを持つ現行順を維持する。
全1,080試行の最大レイテンシは1.59秒、timeout失敗と5秒以上の試行は0件だったため、
request timeoutを12秒から5秒へ短縮した（全backend失敗時の上限36秒→15秒）。

詳細: [`docs/backend-audit.md`](../docs/backend-audit.md)
