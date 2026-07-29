# [analysis] ネガティブシグナルの影響分析

## 背景
ranking_scorer.rs は not_interested / block_author / mute_author / report /
not_dwelled に負の重みを持つ。負スコアは
(combined + negative_sum) / total_sum * NEGATIVE_SCORES_OFFSET で圧縮される。

## 検証方法
offset_score() を weights.json のパラメータ付きで再実装し、
負シグナル確率が上がったときのスコア遷移を可視化する。

## 完了条件

- [x] positive/negative/total sumを上流と同じaction集合で算出する
- [x] `total_sum == 0`、負、非負の3分岐を再実装する
- [x] 5負シグナル単独・同時の確率sweepを出力する
- [x] combined scoreが0を横切る確率を算出する
- [x] terminal表・JSON出力と回帰testを追加する
- [x] 本番重み・offsetが非公開であることを明記する

## 実装

```bash
python scripts/analyze_negative_signals.py \
  --unit-negative-weights --negative-scores-offset 0.1
```

`--unit-negative-weights`は本番値ではなく、各負重みを`-1`に固定した無次元の
感度分析です。詳細は`docs/sensitivity-analysis.md`を参照。
