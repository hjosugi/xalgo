# [analysis] 閲覧者別For You snapshotで代理スコアを評価する

## 背景

公開countは全閲覧者・全期間の事後結果であり、Phoenixの閲覧者別serving予測ではない。
直接検証に近づけるには、同一viewer・同一requestの候補集合と表示順位が必要になる。

## 完了条件

- [x] cookie/tokenを保存しない匿名化snapshot schemaを定義する
- [x] request時刻、position、network内外、media、候補集合を記録する
- [x] NDCG@K、Kendall/Spearman、top-K overlapを算出する
- [x] position/exposure/selection biasの限界をreportへ明記する
- [x] 低・中・高view帯で層別評価できる
- [ ] 実cohortを用いてauthor-disjoint評価する
- [x] input snapshot、commit、設定から結果を再生成できる

## 2026-08-26 author-disjoint実装

`scripts/estimate_feed_weights.py`はtrain/testで同じsaltの`author_hash`を要求し、author/postが
1件でも重複すれば失敗する。held-out pairwise accuracy、Spearman、Kendall tau-bと入力/tool
SHA-256を出力する。上の未完了条件をcheckするには、synthetic fixtureではなくユーザーが
安全に匿名化した実viewer cohortが必要になる。

詳細: [`docs/weight-estimation.md`](../docs/weight-estimation.md)
