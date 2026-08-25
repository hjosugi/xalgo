# Phoenix mini ローカル推論 receipt

> [!NOTE]
> これは廃止済み2026年5月demo artifactの再現receiptです。現行の2026年8月source世代に
> checkpointを移植した結果ではありません。現行契約は
> [`upstream-2026-08.md`](upstream-2026-08.md)を参照してください。

2026-07-30、公式 `xai-org/x-algorithm` の固定commitとGit LFS artifactを使い、
retrievalからrankingまでの公開pipelineをローカルCPUで完走した。これは本番For Youの
再現ではなく、配布されたmini modelと合成example historyに対する実行結果である。

## 再現対象

| 項目 | 固定値・実測値 |
|---|---|
| upstream | `xai-org/x-algorithm@0bfc2795d308f90032544322747caacd535f75ae` |
| LFS artifact SHA-256 | `fbc6017d00588754e22e0c7eb2f786a008a74d309c03c8085fa2fad418a83dac` |
| archive | 2,903,518,802 bytes |
| 展開後 | 3,124,043,128 bytes |
| example sequence SHA-256 | `ec53ed1d58f8b69aa6ee121e8cf1090e10e89cf4cd635ccf22b3d314d50838e7` |
| instrumentation patch SHA-256 | `388669a966c24c64a9225e3545aa8a1f4173962ed078bd639fe2d8879f32638c` |
| probability export SHA-256 | `7214149cc04f68a451849b00f49fef78debb5b7471adb3d4bf463754d6d84e47` |

ZIP全entryのCRC検査とLFS SHA-256照合を通した。machine-readableな固定値は
[`state/phoenix_inference_baseline.json`](../state/phoenix_inference_baseline.json)に
保存している。

artifact実体のretrieval/ranker configはいずれも128次元、4層、4 heads、history 127、
candidate batch 64、output 19列だった。root READMEの256次元・2層という説明とは
一致しない。またPhoenix READMEはsports corpusを約537K件と説明するが、配布実体は
**84,564件 × 128次元**だった。

## 実行

Python 3.13.13、JAX 0.8.1、8 CPU、約22 GiB RAMの環境で、upstream unit testは
34件すべて成功した。公式スクリプトを変更せず実行した結果は次のとおり。

- user `12345`、history 3件
- corpus 84,564件からtop 200をretrieval
- retrieval score範囲 `[0.8790, 0.9382]`
- 200候補を19 headでranking
- デモweighted score範囲 `[0.0022, 0.3922]`
- wall time 15.8秒

全出力を観測するため、固定upstream checkoutへ
[`export_probabilities.patch`](../experiments/phoenix/export_probabilities.patch)を適用した。
追加するのは計算済み`all_probs`のJSON出力だけで、retrieval、ranker、重み付き順位は
変更しない。同じ条件で2回出力し、145,224 byteのJSONがバイト単位で一致した。

```bash
git -C /path/to/x-algorithm checkout 0bfc2795d308f90032544322747caacd535f75ae
git -C /path/to/x-algorithm apply /path/to/xalgo/experiments/phoenix/export_probabilities.patch
cd /path/to/x-algorithm/phoenix
uv sync --frozen
uv run run_pipeline.py \
  --artifacts_dir /path/to/oss-phoenix-artifacts \
  --top_k_retrieval 200 \
  --top_k_display 0 \
  --probabilities_output /tmp/phoenix-probabilities.json
python /path/to/xalgo/scripts/analyze_phoenix_probabilities.py \
  /tmp/phoenix-probabilities.json
```

## 19列の確率分布

binは順に`[0,.001)`, `[.001,.01)`, `[.01,.05)`, `[.05,.1)`, `[.1,.25)`,
`[.25,.5)`, `[.5,.75)`, `[.75,1]`で、各行の合計は200である。

`runners.py label`は公開コードに書かれた並びを参考表示しただけである。
`run_pipeline.py`が選ぶindexと衝突し、checkpointにもhead名metadataがないため、
semantic labelは未確定である。

| col | `runners.py` label（未確定） | mean | median | p95 | max | histogram counts |
|---:|---|---:|---:|---:|---:|---|
| 0 | favorite | 1.053e-6 | 9.919e-8 | 2.727e-6 | 1.020e-4 | 200,0,0,0,0,0,0,0 |
| 1 | reply | 0.06259 | 0.04346 | 0.1826 | 0.2930 | 5,46,61,42,43,3,0,0 |
| 2 | repost | 3.464e-4 | 1.092e-4 | 7.843e-4 | 0.01636 | 194,4,2,0,0,0,0,0 |
| 3 | photo expand | 1.852e-6 | 5.700e-7 | 4.515e-6 | 7.057e-5 | 200,0,0,0,0,0,0,0 |
| 4 | click | 1.960e-4 | 1.159e-4 | 6.495e-4 | 0.002045 | 198,2,0,0,0,0,0,0 |
| 5 | profile click | 8.211e-5 | 4.983e-5 | 2.622e-4 | 6.294e-4 | 200,0,0,0,0,0,0,0 |
| 6 | VQV | 0.005277 | 0.003159 | 0.01543 | 0.03394 | 46,118,36,0,0,0,0,0 |
| 7 | share | 1.304e-6 | 3.055e-7 | 5.442e-6 | 3.314e-5 | 200,0,0,0,0,0,0,0 |
| 8 | share via DM | 8.435e-7 | 1.588e-7 | 1.460e-6 | 7.486e-5 | 200,0,0,0,0,0,0,0 |
| 9 | copy link | 1.395e-6 | 8.307e-7 | 3.725e-6 | 1.776e-5 | 200,0,0,0,0,0,0,0 |
| 10 | dwell | 1.225e-6 | 2.459e-7 | 4.813e-6 | 7.057e-5 | 200,0,0,0,0,0,0,0 |
| 11 | quote | 0.2065 | 0.1890 | 0.4633 | 0.5469 | 0,6,36,26,51,77,4,0 |
| 12 | quoted click | 0.7054 | 0.7109 | 0.9688 | 0.9922 | 0,0,0,0,0,34,78,88 |
| 13 | follow author | 0.04761 | 0.03540 | 0.1350 | 0.2080 | 5,40,76,50,29,0,0,0 |
| 14 | not interested | 2.660e-4 | 1.535e-4 | 9.705e-4 | 0.003159 | 191,9,0,0,0,0,0,0 |
| 15 | block author | 1.817e-4 | 6.199e-5 | 3.362e-4 | 0.01599 | 199,0,1,0,0,0,0,0 |
| 16 | mute author | 5.592e-6 | 3.725e-6 | 1.776e-5 | 3.767e-5 | 200,0,0,0,0,0,0,0 |
| 17 | report | 2.268e-5 | 1.466e-5 | 5.561e-5 | 2.785e-4 | 200,0,0,0,0,0,0,0 |
| 18 | dwell time | 4.110e-7 | 6.799e-8 | 9.559e-7 | 3.767e-5 | 200,0,0,0,0,0,0,0 |

## 公開count proxyとの比較

2026-07-30 06:22 UTCに`validate_popular.py`の組み込み標本を再取得し、成功した10件の
`count / views`を集計した。

| 公開proxy | mean | median |
|---|---:|---:|
| likes / views | 0.01463 | 0.009011 |
| replies / views | 0.002005 | 0.00007075 |
| retweets / views | 0.003081 | 0.0003609 |

head契約の解釈だけで比較対象列が変わる。たとえばfavoriteのモデル中央値は、
`run_pipeline.py`のindexならcol 1の`0.04346`だが、`runners.py`の並びならcol 0の
`9.919e-8`になる。replyはcol 4の`1.159e-4`対col 1の`0.04346`、retweet/repostは
col 6の`0.003159`対col 2の`1.092e-4`である。

さらに二つの標本はcandidate、viewer、履歴、露出時刻、topicが一致していない。
したがって、この比較からcalibration誤差やcandidate単位の相関は計算できない。
確認できたのは次の境界である。

1. 公開count率とPhoenix出力は同じ量ではなく、相互に置換できない。
2. head順を確定しない限り、action別の分布比較自体が一意に定まらない。
3. example history 1件・sports corpusだけなので、非sportsへの一般化は評価できない。
4. 実用的な次段階は、head契約の上流確認と、同意を得たviewer別候補の時点整合標本である。

このためxalgoは引き続き公開count値を「感度分析用proxy」と表示し、Phoenix probabilityや
本番scoreとは呼ばない。
