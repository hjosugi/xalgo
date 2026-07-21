# [analysis] ネガティブシグナルの影響分析

## 背景
ranking_scorer.rs は not_interested / block_author / mute_author / report /
not_dwelled に負の重みを持つ。負スコアは
(combined + negative_sum) / total_sum * NEGATIVE_SCORES_OFFSET で圧縮される。

## 検証方法
offset_score() を weights.json のパラメータ付きで再実装し、
負シグナル確率が上がったときのスコア遷移を可視化する。
