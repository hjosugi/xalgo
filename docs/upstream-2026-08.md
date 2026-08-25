# 2026年8月 upstream 取り込み

基準: `xai-org/x-algorithm` commit
[`d011592a1c`](https://github.com/xai-org/x-algorithm/commit/d011592a1c8c4bfb23781ff15577a68dc08bdde1)
（2026-08-24）。

## 結論

2026年8月13日の公開更新は、5月版 Phoenix demo の小改修ではない。配布 checkpoint、
`run_pipeline.py`、`runners.py` を廃止し、学習・serving・合成データ生成を含む別世代の
Phoenix source を公開した。同時に Home Mixer の feature-switch default が追加され、
重み、VQV閾値、author diversity、OON補正、negative offset の既定値をコードから
検証できるようになった。

これらは公開された**既定値**であり、すべての live request に固定された値とは限らない。
実験・viewer・request context による上書きは xalgo から観測できない。また xalgo の
`count / views` は Phoenix の閲覧者別予測ではないため、公開値を使っても本番順位の
再現にはならない。

## 公開された scoring contract

| 項目 | 公開 default |
|---|---:|
| favorite / reply / retweet / quote | 0.5 / 5.0 / 1.0 / 5.0 |
| share / share via DM / copy link | 2.0 / 5.0 / 20.0 |
| not interested / block / mute / report | -43.2 / -31.2 / -58.8 / -234.0 |
| VQV weight / strict duration gate | 0.05 / `video_duration_ms > 10000` |
| continuous dwell / post unexplored | 0.004 / 0.02 |
| negative score offset | 0.001 |
| author diversity decay / floor | 0.5 / 0.25 |
| OON / topic OON factor | 0.75 / 0.5 |

全26項目と周辺 gate は [`weights.json`](../weights.json) および
[`state/model_contract_baseline.json`](../state/model_contract_baseline.json) に固定した。
値の出典は upstream の `home-mixer/params/param.rs` と
`home-mixer/params/config.rs` である。

Phoenix の公開 profile は次のとおり。

| profile | D | layers | query/KV heads | history | candidates |
|---|---:|---:|---:|---:|---:|
| ranking `xrecsys_seqpack` | 2560 | 8 | 20 / 4 | 1022 | 64 |
| ranking `home_direct_packed_nano` | 512 | 4 | 4 / 2 | 1022 | 64 |
| retrieval `xrecsys_two_tower` | 1024 | 8 | 16 / 4 | 1023 | 64 |
| retrieval `xrecsys_two_tower_nano` | 512 | 4 | 4 / 2 | 1022 | 64 |

旧 demo の `D=128 / 4 layers / 19 outputs` と直接比較できる同一モデルの更新ではない。
現行 source は60 discrete action typeを64列へpadし、continuous actionを8 slot持つ。

## Issue #14–#20 の取り込み

| Issue | upstream commit | xalgoでの扱い |
|---|---|---|
| [#14](https://github.com/hjosugi/xalgo/issues/14) | `47c1bcdadf` | 新世代 source、公開重み、filter/labeling系を基準化。旧 tracker が README 以外を見落としたため、新 Phoenix/config/policy path を回帰 corpus へ追加 |
| [#15](https://github.com/hjosugi/xalgo/issues/15) | `c65aa179db` | 「重みはcountでなく予測値へ掛ける」を明記。Brazil 2026 filter と cold-start Thompson sampling（default off）を記録 |
| [#16](https://github.com/hjosugi/xalgo/issues/16) | `b089ce6489` | semantic-ID prefix gap を含む slate diversity と reply-ranking follower threshold 40,000 を記録 |
| [#17](https://github.com/hjosugi/xalgo/issues/17) | `11a71f87d6` | Following 専用 visibility hydration と threshold 60,000 を記録 |
| [#18](https://github.com/hjosugi/xalgo/issues/18) | `aad7179773`, `d0cef2f943` | quote/ancestor text を対象にした muted-keyword filter、AI trend feedback、served slate context を記録 |
| [#19](https://github.com/hjosugi/xalgo/issues/19) | `28e414f535` | threshold 80,000 と Phoenix source/config 更新を追跡対象化 |
| [#20](https://github.com/hjosugi/xalgo/issues/20) | `d011592a1c` | threshold 100,000、reply-ranking cache fanout、visibility reference compare を追跡対象化 |

reply-ranking follower threshold は `15k → 30k → 40k → 60k → 80k → 100k` と短期間に
変化した。これは Phoenix action weight ではなく Grox reply-spam flow の適用条件であり、
`weights.json` には混ぜない。

## 既存 analysis issue への影響

- [#1](https://github.com/hjosugi/xalgo/issues/1): 公開 default の逆推定は不要になった。
  live override や viewer別予測を推定する課題は残る。
- [#6](https://github.com/hjosugi/xalgo/issues/6): VQV default は10,000 ms / 0.05と確定した。
  観測データによる閾値探索は因果推定ではなく、live override の探索として位置づけ直す。
- [#9](https://github.com/hjosugi/xalgo/issues/9): 旧6 indexの不整合は修正ではなく、
  参照ファイルごと廃止された。履歴 receipt は5月版の再現資料として残す。
- [#10](https://github.com/hjosugi/xalgo/issues/10): 旧 README/artifact drift は新世代 sourceへの
  置換で終了した。新 baseline は source config と Home Mixer default を監査する。
- [#11](https://github.com/hjosugi/xalgo/issues/11): 実 cohort の
  author-disjoint viewer-feed評価は今回も未実施で、引き続き外部データが必要。

## 再現

```bash
nix develop
python scripts/audit_model_contract.py --ref main
python scripts/audit_model_contract.py --ref main --json --fail-on-drift
python -m xalgo.cli score <URL> --preset upstream_2026_08 --json
python scripts/analyze_vqv_threshold.py --thresholds-ms 0,5000,10000,30000
```

旧5月版契約は次で引き続き検査できる。

```bash
python scripts/audit_model_contract.py \
  --ref 0bfc2795d308f90032544322747caacd535f75ae \
  --no-baseline
```
