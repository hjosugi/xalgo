# [analysis] 本番重み係数の逆推定

## 仮説
本番の重み (feature switch 経由、非公開) は、多数のポストの表示順位と
公開エンゲージメント率から回帰で近似できる。

## 検証方法
1. 同一トピック・同時間帯のポストを50件以上 `xalgo score --json` で収集
2. For You 上の実際の表示順を目視記録
3. p_hat ベクトルに対し順位を目的変数として学習 (learning-to-rank)
4. repo_demo（ラベル上はfav 1.0 / reply 0.5 / rt 0.3 / dwell 0.2。ただし公開デモの
   action index不整合あり）と比較

## 注意
Phoenix はパーソナライズ予測なので、単一アカウント観測ではその人固有の重み近似になる。

## 2026-08-26 実装

`scripts/estimate_feed_weights.py`にpairwise logistic learning-to-rankを実装した。
`p_ACTION`特徴、入力/tool SHA-256、公開2026年8月defaultとの比較を出力し、別test CSVの
author/post overlapが0でなければ失敗する。実データのminimum gateはtrain 50行/test 20行。

```bash
python scripts/estimate_feed_weights.py train.csv --test-csv test.csv --json
```

公開default自体は`weights.json::upstream_2026_08`で利用可能になった。live overrideや
viewer別Phoenix予測を推定したと断定するには、synthetic fixtureではなく匿名化した実cohortが
必要であり、出力はcohort内の関連として解釈する。

詳細: [`docs/weight-estimation.md`](../docs/weight-estimation.md)
