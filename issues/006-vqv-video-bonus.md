# [analysis] 動画 VQV ボーナスの条件分析

## 背景
vqv_weight は video_duration_ms > MIN_VIDEO_DURATION_MS のときのみ有効
(weighted_scorer.rs / candidates_util)。閾値は非公開。

## 検証方法
長さの異なる動画ポストの伸び方を比較し、閾値と VQV 寄与を推定。
--vqv-p フラグで感度分析。

## 完了条件

- [x] 上流の厳密な`video_duration_ms > MIN_VIDEO_DURATION_MS`条件を再現する
- [x] 閾値、VQV確率、VQV重みを仮説値としてsweepできる
- [x] 同一投稿の繰り返しsnapshotからviews/hourを比較できる
- [x] credential列を拒否し、input/tool SHA-256から結果を再生成できる
- [x] 閾値・重みが非公開で、観測差から因果効果を断定できない限界を明記する
- [ ] 実動画cohortを複数時点で収集し、author/topic/timeを層別した結果を記録する

## 実装

```bash
python scripts/analyze_vqv_threshold.py \
  --durations-ms 2000,5000,10000,30000 \
  --thresholds-ms 0,5000,10000,30000 --vqv-p 0.1 --vqv-weight 1
python scripts/analyze_vqv_threshold.py \
  --snapshots examples/vqv_snapshots.example.csv --json
```

URLスコアでも`--vqv-min-duration-ms`を指定すると、取得した動画長が仮説閾値を
厳密に超えた場合だけ`--vqv-p`を適用する。動画長を取得できないfallbackでは0扱いとする。
