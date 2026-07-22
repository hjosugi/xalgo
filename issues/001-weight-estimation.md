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
