# [analysis] 動画 VQV ボーナスの条件分析

## 背景
vqv_weight は video_duration_ms > MIN_VIDEO_DURATION_MS のときのみ有効
(weighted_scorer.rs / candidates_util)。閾値は非公開。

## 検証方法
長さの異なる動画ポストの伸び方を比較し、閾値と VQV 寄与を推定。
--vqv-p フラグで感度分析。
