# 2026年9月 upstream 取り込み

基準: `xai-org/x-algorithm` commit
[`8b25829717`](https://github.com/xai-org/x-algorithm/commit/8b25829717a4f104dd04403ee7d0253c5fedb1b7)
（2026-09-18）。前回基準は [`d011592a1c`](upstream-2026-08.md)（2026-08-24）で、
その間に main へ 20 commit が入り、追跡 workflow は Issue #21–#36 として起票した。

その後の 9/22・9/23 の 2 commit（Issue #37・#38）は
[追補](#追補-issue-3738-の取り込み)で扱い、監査 baseline は
[`1b3fec20bc`](https://github.com/xai-org/x-algorithm/commit/1b3fec20bc3fd9879bc3e9f3d9c42753cdc3fede)
（2026-09-23）へ進めた。公開 scoring 既定値はこの 2 commit でも変わっていない。

## 結論

Home Mixer の公開 scoring 既定値 26 項目のうち **3 項目が変わった**。いずれも
2026-08-25 の sync commit [`0d3cdd806c`](https://github.com/xai-org/x-algorithm/commit/0d3cdd806c405f04db7030f720b48687aa304061)
で入り、その後 9 月 18 日まで動いていない。

| 項目 | 8月既定値 | 9月既定値 |
|---|---:|---:|
| VQV weight (`rust_home_mixer_vqv_weight`) | 0.05 | **0.0** |
| dwell weight (`rust_home_mixer_dwell_weight`) | 0.0 | **0.05** |
| video open weight (`rust_home_mixer_video_open_weight`) | 0.05 | **0.07** |

残る 23 項目、negative score offset 0.001、VQV duration gate 10,000 ms、author
diversity 0.5 / 0.25、OON 0.75 / topic OON 0.5、Phoenix の 4 model profile、
action-space 寸法（60 discrete / 64 padded / 8 continuous）は 8 月と同じである。
`scripts/audit_model_contract.py --ref 8b25829717` と再記録した
[`state/model_contract_baseline.json`](../state/model_contract_baseline.json) の差分は 0 件。

VQV weight が 0 になったことで、公開既定値では video quality view の予測は score に
寄与しない。duration gate（10 秒超）は source に残っているが、weight が override
されない限り空振りである。代わりに dwell head が 0.05 で有効になった。8 月時点の
「VQV は default 0.05 で確定」という結論（[#6](https://github.com/hjosugi/xalgo/issues/6)）は
9 月 source では成り立たない。

## scoring 契約の構造変化

数式の形は 8 月と同じ（`offset_score` の 3 分岐は不変）だが、実装の組み方が変わった。

- **正規化 sum の置き場所**（9/18, `8b25829717`）。`positive_sum` / `negative_sum` は
  `from_params` 内の `let` 束縛から `recompute_sums(&mut self)` へ移り、
  `negative_sum` は `self` への代入になった。weight perturbation 後に再計算するためで、
  sum に含める action の集合（positive 18 / negative 5）は変わっていない。8 月の
  監査 parser は `let negative_sum` を前提にしていたため 9 月 source で失敗し、
  今回両方の形を読むようにした。
- **候補ごとの項の正負分割は符号ベース**で、これは 8 月世代の初回 commit
  （`47c1bcdadf`, 8/13）からそうだった。各項 `t` を
  `if t >= 0.0 { pos += t } else { neg -= t }` で振り分け、正規化に使う
  `negative_sum` / `total_sum` は action クラス単位で持つ。公開重みの符号が変わらない
  限り両者は一致するので、xalgo の `normalization_sums` と browser scoring は
  変更していない。8 月の baseline はこの規則を記録していなかったため、今回
  `term_split: by_sign` として契約に加えた。perturbation や override で符号が反転する
  重みが現れれば、ここが効く。
- **weight perturbation**（9/08, `49815da255`）。`WeightPerturbationSigma`（default 0.0）
  が正なら 26 head の重みへ `exp(±σ)` を掛ける。符号は `md5(salt:user_id:head)` の
  最下位 bit で決まり、viewer ごとに固定される。既定値では無効。
- **`MultiplierPreOffset`**（8/25, default `false`）。`true` の場合 author diversity と
  OON の乗数を offset 前の `pos - neg` に掛けてから `offset_score` を通す。既定値では
  従来どおり offset 後に掛ける経路。
- **dwell-regret / value model gate の撤去**（9/18）。8 月 source にあった
  `ValueModelMode`（default `"weighted"`）、`DwellRegret*` の 17 param、
  `value_model_gate.rs` が削除され、`WEIGHTED_VALUE_MODEL_MODE` 定数だけが残った。
  既定値は元々 weighted だったため公開契約への影響はない。
- **click-dwell の扱い**（9/17, `42266f3e2b`）。`EnableClickDwellLowFavRatePenalty` と
  baseline / alpha / floor / cap の 4 param が `EnableCdwellOnImpr`（default `false`）に
  置き換わった。有効時は click dwell time に click 確率を掛ける。
- **cold start**（8/25, 9/04, 9/18）。`ColdStartMaxPostAgeSecs` 86,400 → 172,800、
  `ColdStartTsTopK` 5 → 2、`PhoenixColdStartMaxResults`（default 0）が追加。
  `author_cold_start.rs` は 2 回書き直された。Thompson sampling 自体は default off のまま。
- **fav holdout filter**（9/17, `EnableFavHoldout` default `false`）。

Phoenix 側は retrieval の semantic-ID 経路（`recsys_sid.py`, 9/01）、`loss_recsys.py` と
`ads_head_masking.py`（9/16–9/18）、aggregation type の `DENSE_WITH_LONG_DWELL` への
変更（8/25）が主で、公開 profile の寸法は変わっていない。

## Issue #21–#36 の取り込み

| Issue | upstream commit | 主な内容 | xalgo での扱い |
|---|---|---|---|
| [#21](https://github.com/hjosugi/xalgo/issues/21) | `0d3cdd806c`, `45b48ba6ba` | VQV 0 / dwell 0.05 / video_open 0.07、`MultiplierPreOffset`、Brazil 2026 election filter、reply-spam flow、abuse-enforcement-service | `upstream_2026_09` preset を追加し既定化。3 値を receipt 化 |
| [#22](https://github.com/hjosugi/xalgo/issues/22) | `24c60942c5` | muted-keyword filter、blender selector、visibility safety-label warmer | policy 変更として記録。scoring 影響なし |
| [#23](https://github.com/hjosugi/xalgo/issues/23) | `bc8e5f0f07` | `RerankerHeadTag`、visibility rules の golden corpus / fixtures 追加 | 記録のみ |
| [#24](https://github.com/hjosugi/xalgo/issues/24) | `7ba776848b`, `6384ca7d2c` | Phoenix `recsys_sid.py`（retrieval SID）、visibility rules を `rule_spec` / `author_rules` / `tweet_rules` へ再編、PTOS special video | model profile 寸法不変を監査で確認 |
| [#25](https://github.com/hjosugi/xalgo/issues/25) | `85ac72a1bb` | phoenix scorer / query model、scarecrow XReview intake、safety label source | 記録のみ |
| [#26](https://github.com/hjosugi/xalgo/issues/26) | `e4dcedd3b2` | 外部 PR #88: in-network VF id の重複排除 | 記録のみ。PR API が再び観測できた例として追跡評価に有用 |
| [#27](https://github.com/hjosugi/xalgo/issues/27) | `902a06fd61`, `9b0dc31969` | `author_cold_start.rs` 書き直し、engagement counts hydrator、multi-step reply spam、Phoenix attention / remat | cold start 変更を記録 |
| [#28](https://github.com/hjosugi/xalgo/issues/28) | `49815da255` | weight perturbation、candidate-pipeline framework 改修、`content_features.rs`、quote / media hydrator | `weight_perturbation_sigma` を監査項目に追加 |
| [#29](https://github.com/hjosugi/xalgo/issues/29) | `75d93d9b6c` | VF candidate hydrator / filter、candidate-pipeline、Phoenix README | 記録のみ |
| [#30](https://github.com/hjosugi/xalgo/issues/30) | `fee1d0f3e9` | two-tower model、visibility clock cache / hydration | 記録のみ |
| [#31](https://github.com/hjosugi/xalgo/issues/31) | `6bb4594253` | Brazil election filter、phoenix candidate pipeline | 記録のみ |
| [#32](https://github.com/hjosugi/xalgo/issues/32) | `2d4a03c2db` | `tweet_type_metrics_hydrator.rs`、two-tower config | 記録のみ |
| [#33](https://github.com/hjosugi/xalgo/issues/33) | `fad2f71edc` | Phoenix `loss_recsys.py` / `recsys_feature_prep.py` / `recsys_model.py` | profile 寸法不変を確認 |
| [#34](https://github.com/hjosugi/xalgo/issues/34) | `42266f3e2b` | `EnableCdwellOnImpr`、fav holdout filter、cold start | `cdwell_on_impr` を監査項目に追加 |
| [#35](https://github.com/hjosugi/xalgo/issues/35) | `c279172eb8` | `ads_head_masking.py`、loss、Brazil election filter | 記録のみ |
| [#36](https://github.com/hjosugi/xalgo/issues/36) | `8b25829717` | dwell-regret / value model gate 撤去、符号ベース分割、`PhoenixColdStartMaxResults` | 監査 parser を 9 月 source 形へ対応、`term_split` を契約化、baseline を再記録 |

追跡 workflow の 16 件はすべて「ranking に関係する変更」として正しく起票されていた。
20 commit のうち scoring 既定値を動かしたのは 1 件（`0d3cdd806c`）、scoring 実装を
動かしたのは 4 件（`0d3cdd806c`, `49815da255`, `42266f3e2b`, `8b25829717`）で、残りは
candidate pipeline、visibility-filtering、Grox policy、Phoenix 学習側の変更である。

## xalgo 側の変更

- [`weights.json`](../weights.json): `upstream_2026_09` preset（source `8b25829717`、
  introduced `0d3cdd806c`）を追加し `default_preset` に設定。`upstream_2026_08` は
  8 月比較用として残す。
- [`scripts/audit_model_contract.py`](../scripts/audit_model_contract.py):
  `self.negative_sum = ...` 形の sum を読めるようにし、`multiplier_pre_offset`、
  `weight_perturbation_sigma`、`cdwell_on_impr` を optional setting として、
  `term_split` と `weight_perturbation_supported` を scoring 契約として記録する。
  8 月以前の ref も引き続き監査できる。
- [`state/model_contract_baseline.json`](../state/model_contract_baseline.json):
  `8b25829717` で再記録（2026-09-22）。
- [`scripts/analyze_vqv_threshold.py`](../scripts/analyze_vqv_threshold.py): 公開既定 VQV
  weight 0.0 と、8 月値 0.05 を仮説値として区別して出力する。
- [`scripts/estimate_feed_weights.py`](../scripts/estimate_feed_weights.py): 公開既定との
  比較先を weights.json の既定 preset にし、`public_default_preset` を報告に含める。
- 学習ラボ（`web/`）は 9 月 preset を既定にし、8 月 preset との差を preset 説明に示す。

## 既存 analysis issue への影響

- [#1](https://github.com/hjosugi/xalgo/issues/1): 公開既定値が 8 月 → 9 月で動いた。
  snapshot から推定した重みの比較先は `upstream_2026_09` になる。8 月 snapshot を
  評価する場合は `--weights` に 8 月 preset を既定にした weights.json を渡すこと。
- [#6](https://github.com/hjosugi/xalgo/issues/6): VQV default は 0.0 に変わった。
  duration gate の閾値探索は「live override で VQV が有効化されているか」の探索として
  のみ意味を持つ。
- [#11](https://github.com/hjosugi/xalgo/issues/11): 実 cohort の author-disjoint
  viewer-feed 評価は今回も未実施。引き続き外部データが必要で、open のまま。

## 追補: Issue #37–#38 の取り込み

基準 `8b25829717` の後に main へ入った 2 commit を読んだ。どちらも公開 scoring 既定値
26 項目、negative score offset、VQV duration gate、author diversity、OON / topic OON、
Phoenix の 4 model profile、action-space 寸法を**動かしていない**。
`scripts/audit_model_contract.py --ref 1b3fec20bc` の旧 baseline との差分 6 件は、
すべて今回監査に加えた記録項目（下記）で、既存項目の値の差分は 0 件だった。

| Issue | upstream commit | 主な内容 | xalgo での扱い |
|---|---|---|---|
| [#37](https://github.com/hjosugi/xalgo/issues/37) | [`3aa0fa336c`](https://github.com/xai-org/x-algorithm/commit/3aa0fa336c4a20e4149b6151629b6050897bb8a5)（9/22） | `NEW_USER_OON_WEIGHT_FACTOR` 定数を `NewUserOonWeightFactor` param へ昇格（既定 0.00001 のまま）、SimClusters ANN の候補年齢上限 48h を `SimclustersMaxCandidateAgeHours` param 化、retrieval 候補の Kafka side effect、`PhoenixMoeColdStartMaxResults`（0）追加、cold start が lift 先 rank と MoE author policy による 0 化を候補に記録、VM ranker へ value-model 入力（既定 off）、dedup filter が重複候補の retrieval source を統合、Phoenix の bloom / topic serving filter を model runner へ統合、visibility `treatment.rs`、Grox reply-spam の simple scorer が full scorer へ委譲 | new-user OON 係数と年齢閾値、`NEW_USER_MIN_FOLLOWING` を監査項目に追加（定数時代の ref も同じ値で読む）。preset に記録 |
| [#38](https://github.com/hjosugi/xalgo/issues/38) | [`1b3fec20bc`](https://github.com/xai-org/x-algorithm/commit/1b3fec20bc3fd9879bc3e9f3d9c42753cdc3fede)（9/23） | `unoffset_score` を追加し `MultiplierPreOffset` 分岐の net を `pos - neg` から `unoffset_score(weighted)` へ変更、`CachedPostsReuseWeightedScore`（既定 `false`）、MoE retrieval 既定の入れ替え（cluster `Experiment3Memy04` → `Experiment2Memy04`、`PhoenixMOEMaxResults` 200 → 0、`PhoenixMoeColdStartMaxResults` 0 → 200）、VM ranker の debias payload（既定 off）、Grox PTOS key-frames filter、visibility conversation-control hydrator | `pre_offset_net` と `unoffset_inverts_offset` を scoring 契約へ、`cached_posts_reuse_weighted_score` を optional setting へ追加。`xalgo.score.unoffset_score` を追加。baseline を `1b3fec20bc` で再記録 |

### scoring への影響

- **new-user OON 係数**（`3aa0fa336c`）。`effective_oon_weight` は、topic 指定があれば
  `TopicOonWeightFactor`、viewer のアカウント作成から `NewUserAgeThresholdSecs` 未満で
  follow 数が `NEW_USER_MIN_FOLLOWING`（5）以上なら `NewUserOonWeightFactor`、それ以外は
  `OonWeightFactor` を返す。係数が param になったので実験で上書きできるようになったが、
  値は 8 月から 0.00001 のままで、年齢閾値の既定は 0 秒なので新規 viewer 分岐は既定では
  発火しない。定数だった ref でも監査は `config.rs` から同じ値を読むので、昇格そのものは
  drift として出ない。
- **pre-offset 分岐の net**（`1b3fec20bc`）。`total_sum` が 0 でなければ `unoffset_score` は
  `offset_score` の厳密な逆関数である。負の net `[-negative_sum, 0)` は `[0, OFFSET)` へ、
  非負の net は `[OFFSET, ∞)` へ写るので、`OFFSET` との比較で分岐すれば元の net に戻る。
  `total_sum` が 0 の場合は offset 側が負値を 0 に丸めるため net も 0 になるが、従来の
  `pos - neg` 経路でも負の net には乗数を掛けずに `offset_score` が 0 に丸めるので、最終
  score は同じになる。したがって既定（`MultiplierPreOffset=false`、
  `CachedPostsReuseWeightedScore=false`）では score は変わらない。変わり得るのは cache
  済み weighted score を再利用する場合で、cache 時と現在で重み（perturbation や override）
  が違うと、現在の sum による逆変換は cache 時の net と一致しない。
- **候補取得**。MoE retrieval は既定で通常枠 0、cold-start 枠 200 になり、MoE source は
  新規 author の候補取得に振り向けられた。SimClusters ANN の 48 時間上限は値を変えずに
  param 化された。どちらも候補集合を変えるが、xalgo が計算する単一 post の score には入らない。
- cold start の lift 先 rank、MoE author policy による 0 化、統合された retrieval source は
  いずれも記録のための変更で、score 値は変えない（VM ranker への入力として送られる）。

### xalgo 側の変更（#37・#38）

- [`scripts/audit_model_contract.py`](../scripts/audit_model_contract.py):
  `new_user_age_threshold_secs` と `cached_posts_reuse_weighted_score` を optional setting に、
  `new_user_oon_weight_factor` を「param 優先、無ければ `config.rs` 定数」の昇格 setting に、
  `new_user_min_following` を scoring 定数に加えた。scoring 契約には pre-offset 分岐の net の
  出所（`pre_offset_net`: `weighted_parts` / `unoffset_weighted_score`）と、`unoffset_score` が
  `offset_score` の逆関数の形をしているか（`unoffset_inverts_offset`）を記録する。
  8 月・9 月前半の ref も引き続き監査できる。
- [`state/model_contract_baseline.json`](../state/model_contract_baseline.json):
  `1b3fec20bc` で再記録（2026-09-24）。
- [`weights.json`](../weights.json): `upstream_2026_09` の `source_ref` を `1b3fec20bc` に進め、
  8 月・9 月 preset に `new_user_oon_weight_factor` / `new_user_age_threshold_secs` を記録。
  26 重みは変更なし。
- [`xalgo/score.py`](../xalgo/score.py): upstream と同じ `unoffset_score` を追加し、公開既定
  重みで `offset_score` との往復が一致することを test で固定した。既定 preset の重み・
  OON 設定・`source_ref` が監査 baseline と一致することも test で確認する。

## 再現

```bash
nix develop
python scripts/audit_model_contract.py --ref 1b3fec20bc3fd9879bc3e9f3d9c42753cdc3fede
python scripts/audit_model_contract.py --ref main --json --fail-on-drift
python -m xalgo.cli score <URL> --preset upstream_2026_09 --json
python -m xalgo.cli score <URL> --preset upstream_2026_08 --json
python scripts/analyze_vqv_threshold.py --thresholds-ms 0,5000,10000,30000
```

9 月前半の契約は `--ref 8b25829717a4f104dd04403ee7d0253c5fedb1b7 --no-baseline` で、
8 月契約は `--ref d011592a1c8c4bfb23781ff15577a68dc08bdde1 --no-baseline` で、
5 月版契約は `--ref 0bfc2795d308f90032544322747caacd535f75ae --no-baseline` で
引き続き監査できる。
