# Author Diversity・VQV・負シグナル感度分析

現行公開コードにはfeature-switch defaultがありますが、live requestでは実験設定などで
上書きされ得ます。ここで扱う結果は、公開defaultまたは指定した仮定に対する再現可能な
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

## VQV duration gate

現行commit `d011592a1c`のHome Mixerは、VQV予測へweightを掛ける前に次の条件を
適用します。

```text
eligible = video_duration_ms > MIN_VIDEO_DURATION_MS
vqv contribution = eligible ? VQV_WEIGHT * P(VQV) : 0
```

比較は`>=`ではなく厳密な`>`です。公開defaultは10,000 ms / 0.05です。ただしlive
overrideとviewer別`P(VQV)`は観測できません。URLスコアではdefaultまたは仮説値を
明示できます。
FxTwitterの`duration`は秒単位なので取得時にmsへ変換します。他のfallback backendでは
動画長を取得できない場合があり、その場合は閾値を満たしたと仮定せずVQVを0扱いします。

```bash
python -m xalgo.cli score <URL> --preset full_template \
  --weight vqv=1 --vqv-p 0.1 --vqv-min-duration-ms 10000
python scripts/analyze_vqv_threshold.py \
  --durations-ms 2000,5000,10000,30000,60000 \
  --thresholds-ms 0,5000,10000,30000 --vqv-p 0.1 --vqv-weight 1
```

`scripts/analyze_vqv_threshold.py`は各閾値について、動画ごとのeligible判定と
`vqv_weight × vqv_p`の寄与を出します。`--snapshots`へ次のCSVを渡すと、同じ投稿の
最初と最後の観測から`views_delta / elapsed_hours`を計算し、eligible/ineligible群の
平均・中央値を併記します。

```csv
post_id,video_duration_ms,observed_at,views
anonymized-a,5000,2026-07-01T00:00:00Z,1000
anonymized-a,5000,2026-07-01T06:00:00Z,1360
```

各投稿には異なる時刻の2行以上が必要です。cookie、token、session等を含む列は拒否します。
例の[`examples/vqv_snapshots.example.csv`](../examples/vqv_snapshots.example.csv)は
入出力確認用の合成データで、実測結果ではありません。JSON出力には入力とtoolのSHA-256が
入り、同じ入力・引数から再生成できます。

取得信頼性監査のprivacy-minimized receiptも直接入力できます。同一cohortのreceiptを
2個以上指定し、既定の`fxtwitter`（または`--backend`指定）のうち、動画長とview countが
両時点以上で取得できた投稿だけを比較します。入力metadataにはreceiptごとのSHA-256、
除外理由別件数、単一観測しかない投稿数を残すため、attritionを確認できます。

```bash
python scripts/analyze_vqv_threshold.py \
  --backend-receipt state/backend-audits/snapshot-01.json \
  --backend-receipt state/backend-audits/snapshot-02.json \
  --strata examples/vqv_strata.example.csv \
  --thresholds-ms 0,5000,10000,30000 \
  --output state/vqv/analysis-current.json --json
```

`--strata`へ渡す補助CSVは`post_id,author_group,topic_group`の3列だけを許可し、
分析対象の全post IDを含む必要があります。著者名、本文、credential等の余分な列は
拒否します。group labelは小文字ASCII、数字、ピリオド、underscore、hyphenの
1–64文字に正規化し、実名ではなく`author-01`のような不透明labelを使用します。
入力例は
[`examples/vqv_strata.example.csv`](../examples/vqv_strata.example.csv)です。
各仮説閾値についてgroupごとのeligible / ineligible成長率を出し、両側に投稿がある
`comparable_group_count`も記録します。

### 2026-07-30 実動画cohortの3時間結果

固定120投稿のbackend監査3回（07:27 / 08:00 / 10:29 UTC、間隔3.03時間）から、
FxTwitterで全時点の動画長とview countを取得できた19動画を比較した。動画長は
9,920–568,416ms、各動画3観測で、単一観測への脱落は0件だった。

- analysis receipt:
  [`state/vqv/analysis-2026-07-30-04.json`](../state/vqv/analysis-2026-07-30-04.json)
- analysis SHA-256:
  `143f549529b9ab79bbf77c3ba24ab28a337886b054d06d0d2f8d5229631f7c5c`
- anonymous strata:
  [`state/vqv/strata-2026-07-30-03.csv`](../state/vqv/strata-2026-07-30-03.csv)
- strata SHA-256:
  `a3e80ad56cf757c2889a5bff51c27a7bd73731ad139e1b2f1aff7d95259d1117`
- tool SHA-256:
  `cba3e105cad65a2be1bf73f6e2e6727b913905b23c3392c0d55489d8f95bd170`
- 19本中6本でviewが増加し、13本は変化なし
- 30日未満の5本は全て増加（合計+1,393 views、平均91.95 views/hour）
- 30日以上の14本は1本だけ+2（平均0.047 views/hour）
- 15秒閾値の平均差（eligible − ineligible）は−39.0 views/hour
- 20秒閾値は−39.4、30秒閾値は−19.9、60秒閾値は−30.7 views/hour

この短い観測では新しい投稿だけが伸びており、動画長より投稿時期の交絡が支配的である。
各群も最大19本と小さいため、負の差をVQVの効果やlive threshold overrideとは解釈しない。投稿30日を
境界に層別しても群間差が極端で、時間交絡を除去できる標本ではない。

公開レスポンスから著者名・本文を保存せず、19件へ不透明なauthor groupと粗いtopic
groupだけを付けた。著者は19件すべて異なるため、全閾値でauthorの
`comparable_group_count`は0だった。topicはfootball 11件、other-sport 3件、
unclassified 5件で、30秒と60秒の仮説では3群とも比較可能だった。30秒の
eligible − ineligible平均差は順に−19.54、0、+2.59 views/hourで方向が揃わず、
60秒では−10.85、0、−90.68だった。手作業の粗いtopic分類、小さいcell、投稿時期との
交絡があるため、層別後の差もVQV閾値の証拠として扱わない。

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
- author decay、floor、VQV閾値・重み、負重み、offsetには公開defaultがあるが、
  live requestのoverrideは観測できない。
- 公開view増加は露出後の観測値であり、動画長以外のauthor、topic、投稿時刻、
  candidate selection、exposureが交絡する。閾値前後の群差はlive overrideや因果効果を特定しない。
- `normalize_score()`の実装は公開スナップショットにないため、この段階は再現しない。
- responseを分けても同じ候補集合・同じ予測値になるという保証はない。
- 感度分析は相関や因果効果の推定ではなく、式の挙動を確認するためのもの。
