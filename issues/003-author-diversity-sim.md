# [analysis] Author Diversity 減衰のシミュレーション

## 式 (author_diversity_scorer.rs)
multiplier(position) = (1 - floor) * decay^position + floor

## 検証方法
decay/floor をグリッドで振り、同一著者の連投がフィード内で
何位まで沈むかをシミュレーション。連投戦略 vs 分散投稿戦略の損益分岐を求める。

## 完了条件

- [x] 上流と同じraw score順・著者出現回数でmultiplierを適用する
- [x] decay/floorの直積gridを評価する
- [x] burstとresponse分割時の順位・top-K件数を比較する
- [x] 無補正スコア維持に必要なbase score上昇率を算出する
- [x] JSON出力と回帰testを追加する
- [x] 投稿間隔の因果効果ではないことを明記する

## 実装

```bash
python scripts/simulate_author_diversity.py
python scripts/simulate_author_diversity.py --json
```

詳細は`docs/sensitivity-analysis.md`を参照。
