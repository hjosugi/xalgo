# Author Diversity・負シグナル感度分析

公開コードに式はありますが、係数は`xai_feature_switches`から注入されるため
本番値は公開されていません。ここで扱う結果は、指定した仮定に対する再現可能な
what-if分析です。実際のFor You順位や投稿戦略の因果効果ではありません。

## Author Diversity

固定commit `0bfc2795d3`の`ranking_scorer.rs`は、候補をweighted scoreの降順に並べ、
同一著者の出現回数`position`へ次を適用します。

```text
multiplier(position) = (1 - floor) * decay^position + floor
adjusted_score       = weighted_score * multiplier(position)
```

`position=0`の最初の候補は常に1.0倍です。カウンタは一つのfeed response内でだけ
増えます。公開コードから「何時間空ければリセットされる」とは読めません。

```bash
python scripts/simulate_author_diversity.py
python scripts/simulate_author_diversity.py \
  --author-scores 1.0,0.94,0.88 \
  --competitor-scores 0.98,0.92,0.86,0.80,0.74 \
  --decays 0.5,0.7,0.9 --floors 0,0.2,0.4 --top-k 5 --json
```

比較する二つのケースは次の通りです。

- `burst`: target authorの全候補を同じresponseへ入れ、2件目以降を減衰する。
- `distributed`: target authorの各候補を別responseへ入れ、各回でカウンタを0に戻す。

`break_even_score_uplift = 1 / multiplier - 1`は、減衰後も無補正時と同じスコアを
保つために必要なbase score上昇率です。competitor候補とPhoenix予測自体は固定するため、
投稿時刻による候補集合や予測値の変化はモデル化していません。

## Negative score offset

同じ固定commitの`ScoringWeights::from_params`と`offset_score()`に合わせ、
`xalgo.score.offset_score()`は次を実装します。

```text
positive_sum = 15個の正アクション重みの合計
negative_sum = -(5個の負アクション重みの合計)
total_sum    = positive_sum + negative_sum

total_sum == 0: max(combined, 0)
combined < 0:  (combined + negative_sum) / total_sum * offset
otherwise:     combined + offset
```

`cont_dwell_time`と`cont_click_dwell_time`はcombined scoreには寄与しますが、
上流実装のnormalization sumには含まれません。5個の負アクションは
`not_interested`、`block_author`、`mute_author`、`report`、`not_dwelled`です。

```bash
python scripts/analyze_negative_signals.py \
  --unit-negative-weights --negative-scores-offset 0.1
python scripts/analyze_negative_signals.py \
  --weight not_interested=-1 --weight block_author=-2 \
  --weight mute_author=-2 --weight report=-10 --weight not_dwelled=-0.5 \
  --negative-scores-offset 0.1 --json
```

最初の例は5負重みをすべて`-1`とする無次元感度分析です。二つ目も仮説値であり、
本番値ではありません。各action単独と5action同時の確率sweep、combined scoreが
0を横切る確率、offset後の値を出力します。

## 解釈上の限界

- Phoenix確率はviewer、履歴、候補集合ごとに変わり、公開countからは直接得られない。
- author decay、floor、負重み、offsetの本番値は非公開。
- `normalize_score()`の実装は公開スナップショットにないため、この段階は再現しない。
- responseを分けても同じ候補集合・同じ予測値になるという保証はない。
- 感度分析は相関や因果効果の推定ではなく、式の挙動を確認するためのもの。
