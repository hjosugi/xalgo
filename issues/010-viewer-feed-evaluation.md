# [analysis] 閲覧者別For You snapshotで代理スコアを評価する

## 背景

公開countは全閲覧者・全期間の事後結果であり、Phoenixの閲覧者別serving予測ではない。
直接検証に近づけるには、同一viewer・同一requestの候補集合と表示順位が必要になる。

## 完了条件

- [ ] cookie/tokenを保存しない匿名化snapshot schemaを定義する
- [ ] request時刻、position、network内外、media、候補集合を記録する
- [ ] NDCG@K、Kendall/Spearman、top-K overlapを算出する
- [ ] position/exposure/selection biasの限界をreportへ明記する
- [ ] 低・中・高view帯とauthor-disjointで層別評価する
- [ ] input snapshot、commit、設定から結果を再生成できる
