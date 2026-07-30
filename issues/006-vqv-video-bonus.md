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
- [x] privacy-minimized backend監査receiptを実動画の繰り返し観測へ直接変換できる
- [x] 閾値・重みが非公開で、観測差から因果効果を断定できない限界を明記する
- [x] 実動画cohortを3時点で収集し、投稿時期で層別した結果を記録する
- [ ] author/topicを匿名化した補助metadataで層別する

## 実装

```bash
python scripts/analyze_vqv_threshold.py \
  --durations-ms 2000,5000,10000,30000 \
  --thresholds-ms 0,5000,10000,30000 --vqv-p 0.1 --vqv-weight 1
python scripts/analyze_vqv_threshold.py \
  --snapshots examples/vqv_snapshots.example.csv --json
python scripts/analyze_vqv_threshold.py \
  --backend-receipt state/backend-audits/snapshot-01.json \
  --backend-receipt state/backend-audits/snapshot-02.json \
  --output state/vqv/analysis-current.json --json
```

URLスコアでも`--vqv-min-duration-ms`を指定すると、取得した動画長が仮説閾値を
厳密に超えた場合だけ`--vqv-p`を適用する。動画長を取得できないfallbackでは0扱いとする。

## 2026-07-30 実測進捗

backend監査の3 receiptを直接読み、全時点で動画長・viewsを持つ19本を3.03時間観測した。
6本が増加し、投稿30日未満の5本は全て増加（+1,393 views）、30日以上の14本は
1本だけ+2だった。
15/20/30/60秒の各仮説でeligible群の平均views/hourはineligible群を下回ったが、
投稿時期との完全な交絡、小標本、短い観測区間があるため閾値の証拠とは扱わない。

分析receipt: `state/vqv/analysis-2026-07-30-03.json`
（SHA-256 `add1a08676b02d47134adb61c1dfb1fb9e38fec15e91d67e80f0a7b21186935a`）

投稿30日を境界に層別しても、投稿時期の群間差が支配的だった。privacy-minimized receiptは
著者と本文を保存しないため、author/topic層別には匿名化した補助metadataが別途必要。
