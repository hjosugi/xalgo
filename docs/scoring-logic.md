# 講義ノート: xalgo のスコアリング

## このノートのゴール
1. 1投稿のスコアがどう決まるか
2. 負の評価がどこで効くか
3. 今の公開既定値

## 0. 一行で
> `score = offset(Σ wᵢ·Pᵢ) × 多様性 × OON`

viewer ごとに「行動確率 × 重み」を足し、負を offset で潰し、最後に多様性と OON を掛ける。

## 1. 入力: P（行動確率）
Phoenix が予測する `P(favorite), P(reply), P(retweet), …`。
xalgo は本物の予測が無いので **公開 count / views** で代用する。

## 2. 重み付き和
```
combined = Σ w(action) × P(action)
```
- **正**（加点）: favorite, reply, retweet, dwell, follow_author, share, …
- **負**（減点）: not_interested, block_author, mute_author, report, not_dwelled
- **条件付き**:
  - `vqv` / `quoted_vqv` → 動画が **10秒超** のときだけ
  - `post_unexplored` → **in-network** のときだけ

## 3. offset（負を正の小さい値へ）
負の `combined` をそのまま使うと、負が強すぎて順位が壊れる。そこで圧縮する。
```
total_sum = positive_sum + negative_sum
combined >= 0  →  combined + 0.001
combined <  0  →  (combined + negative_sum) / total_sum × 0.001
total_sum == 0 →  max(combined, 0)
```
→ 負スコアは `[0, 0.001)` に収まる。

## 4. 多様性・OON（offset の後）
- **author diversity**: 同じ人の連投を減衰
  `(1 - floor) × decay^position + floor`（既定 `decay=0.5, floor=0.25`）
- **OON**（ネットワーク外）: `× 0.75`
  （topic 0.5 / 新規ユーザー 0.00001）

## 5. 例題
`views=1000, likes=100, replies=20, retweets=10`、既定 preset で計算。

| 行動 | P | 重み | 積 |
|---|---:|---:|---:|
| favorite | 0.10 | 0.5 | 0.050 |
| reply | 0.02 | 5.0 | 0.100 |
| retweet | 0.01 | 1.0 | 0.010 |

`combined = 0.160` → 非負なので `offset = 0.160 + 0.001 = 0.161`。
位置0・in-network なので多様性=1、OON=1 → **score = 0.161**。

## 6. 今の公開既定値（`upstream_2026_10` / 2026-09-29〜）
9月から変わったのは3項目だけ。

| 項目 | 9月 | 10月 |
|---|---:|---:|
| click | 0.4 | **0.3** |
| cont_click_dwell_time | 0.0 | **0.4** |
| not_interested | -43.2 | **-47.52** |

他23重み、offset `0.001`、VQV `0.0`、dwell `0.05`、video_open `0.07` は9月と同じ。

## 7. まとめ
- スコアは **重み付き和 → offset → 多様性/OON** の3段。
- 負は offset で `[0, 0.001)` に圧縮される。
- 公開既定値は live の実験設定で上書きされ得る。
