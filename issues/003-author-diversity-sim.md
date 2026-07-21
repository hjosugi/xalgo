# [analysis] Author Diversity 減衰のシミュレーション

## 式 (author_diversity_scorer.rs)
multiplier(position) = (1 - floor) * decay^position + floor

## 検証方法
decay/floor をグリッドで振り、同一著者の連投がフィード内で
何位まで沈むかをシミュレーション。連投戦略 vs 分散投稿戦略の損益分岐を求める。
