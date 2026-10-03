# 2026年9月下旬〜10月 upstream 取り込み

基準: `xai-org/x-algorithm` commit
[`1b3fec20bc`](https://github.com/xai-org/x-algorithm/commit/1b3fec20bc3fd9879bc3e9f3d9c42753cdc3fede)
（2026-09-23、[9月版](upstream-2026-09.md)の追補で確定）。今回の基準は
[`76843a5eea`](https://github.com/xai-org/x-algorithm/commit/76843a5eea278ced444b21372d4e6d6909f5c35e)
（2026-10-02）で、その間に main へ入った 7 commit を追跡 workflow が
Issue #39–#45 として起票した。

## 結論

公開 scoring の既定値は **3 項目が変わった**。すべて 2026-09-29 の
[`a707cc27ba`](https://github.com/xai-org/x-algorithm/commit/a707cc27ba36d3fa79450c9cffcc48a82d080b02)
（Issue #42）で入った。

| 項目 | 9月既定値 | 10月既定値 |
|---|---:|---:|
| click weight (`rust_home_mixer_click_weight`) | 0.4 | **0.3** |
| cont_click_dwell_time weight (`rust_home_mixer_cont_click_dwell_time_weight`) | 0.0 | **0.4** |
| not_interested weight (`rust_home_mixer_not_interested_weight`) | -43.2 | **-47.52** |

残る 23 重み、negative score offset 0.001、VQV duration gate 10,000 ms、author
diversity 0.5 / 0.25、OON 0.75 / topic OON 0.5、new-user OON 0.00001（閾値 0 秒）、
Phoenix の 4 model profile、action-space 寸法（60 discrete / 64 padded / 8
continuous）は 9 月と同じである。`scripts/audit_model_contract.py --ref 76843a5eea`
と再記録した [`state/model_contract_baseline.json`](../state/model_contract_baseline.json)
の旧 baseline との差分は、下記の構造変化と重み 3 件だけだった。

`cont_click_dwell_time` が 0.0 → 0.4 になったのは、`EnableCdwellOnImpr` ゲートが
撤去され、click dwell time が重みどおりに直接寄与するようになったためである。
9 月版の `cdwell_on_impr=false` は「既定では無効」だったが、10 月版では重み自体が
0.4 で有効になった。あわせて `not_interested` の負の重みが強まった。

## scoring 契約の構造変化

9/24 の
[`44d37ebf87`](https://github.com/xai-org/x-algorithm/commit/44d37ebf87f2185b949cd37b710d410c2a77d21f)
（Issue #39）で scoring の実装が Home Mixer の外へ抽出された。数式は 9 月と同じ
（`offset_score` の 3 分岐、`unoffset_score` の逆変換、action クラス単位の
normalization sum）だが、ファイルの置き場所と設定の持ち主が変わった。

- **値モデルの抽出**。`home-mixer/scorers/ranking_scorer.rs`（1255 行）が削除され、
  `home-mixer/scorers/value_model.rs` は `xai-value-model` を呼ぶ薄い adapter に
  なった。実装は新 crate `xai-value-model/`（`scoring.rs`, `weights.rs`,
  `inputs.rs`, `phoenix_scores.rs`）へ移り、README の参照先も
  `xai-value-model/scoring.rs` に変わった。
- **param の移設**。`EnableAuthorDiversity` / `AuthorDiversityDecay` /
  `AuthorDiversityFloor` / `OonWeightFactor` / `TopicOonWeightFactor` /
  `NewUserOonWeightFactor` / `NewUserAgeThresholdSecs` / `MultiplierPreOffset` /
  `EnableOonRescoreForInNetworkRepliesRetweets` / `WeightPerturbationSigma` /
  `WeightPerturbationSalt` は `home-mixer/params/param.rs` から
  `vm-ranker/params.rs` へ移った。既定値は 9 月と同じ。
- **ローカル fallback**。`home-mixer/scorers/value_model.rs` の `weights_for` は
  author diversity・OON rescore・`MultiplierPreOffset` を `false`/`1.0` に固定する。
  公開 count を使う xalgo の単一 post score には影響しないが、契約として記録した。
- **削除された param**。`ContActiveSecs5mResidualNormWeight`（`applied_weights` が
  0.0 を挿入）、`EnableMultiplicativePostUnexplored` /
  `MultiplicativePostUnexploredAlpha`（乗算分岐そのものが消えた）、
  `PostUnexploredWeightInNetworkOnly`（`compute_weighted_score` が in-network の
  ときだけ `post_unexplored` を足す形に固定）、`EnableCdwellOnImpr`、
  `CachedPostsReuseWeightedScore`（`weighted_score` が既にあればそれを使う）が
  消えた。xalgo は削除を `None`（`post_unexplored_in_network_only` は実挙動の
  `true`）として記録する。
- **weight perturbation** は `xai-value-model/weights.rs::perturbed` に移った。
  符号は `md5(salt:user_id:head)` の最下位 bit で決まる点は 9 月と同じ。
- **term split**。新しい `compute_weighted_score` は各項を並べて合計するだけで
  候補ごとの `(pos, neg)` 分割を持たない。normalization は action クラス単位の
  `positive_sum()` / `negative_sum()` を使うため、契約の `term_split` は
  `by_action_class` になった。

## Issue #39–#45 の取り込み

| Issue | upstream commit | 主な内容 | xalgo での扱い |
|---|---|---|---|
| [#39](https://github.com/hjosugi/xalgo/issues/39) | [`44d37ebf87`](https://github.com/xai-org/x-algorithm/commit/44d37ebf87f2185b949cd37b710d410c2a77d21f)（9/24） | `ranking_scorer.rs` を削除し `xai-value-model` crate と `vm-ranker` へ値モデルを抽出、Home Mixer scorer を adapter 化、Phoenix two-tower の dataset capacity / SID、visibility hydration 再編 | 監査を新世代 `source_2026_10` へ対応。重み・設定は `vm-ranker/params.rs`、数式は `xai-value-model/scoring.rs` から読む。baseline を再記録 |
| [#40](https://github.com/hjosugi/xalgo/issues/40) | [`bf7db1becb`](https://github.com/xai-org/x-algorithm/commit/bf7db1becb6590152fba79b8c3bf0555752f7b14)（9/25） | Phoenix `per_layer_l2_weight`（既定 0.0）、visibility hydration の execute/plan 再編、about-this-account client | scoring 既定値の変更なし。記録のみ |
| [#41](https://github.com/hjosugi/xalgo/issues/41) | [`4c5cfe8f07`](https://github.com/xai-org/x-algorithm/commit/4c5cfe8f07f1c76d4f04277e803f20e6039f5191)（9/26） | abuse-enforcement の overturn hold、`author_cold_start` の retrieval gating、Phoenix `ScorePosts` RPC、visibility hydration decode/store | scoring 既定値の変更なし。記録のみ |
| [#42](https://github.com/hjosugi/xalgo/issues/42) | [`a707cc27ba`](https://github.com/xai-org/x-algorithm/commit/a707cc27ba36d3fa79450c9cffcc48a82d080b02)（9/29） | **click 0.4→0.3 / cont_click_dwell_time 0.0→0.4 / not_interested -43.2→-47.52**、cold start の MoE ranking policy 撤去、Phoenix lexical match bucket、abuse-ledger | `upstream_2026_10` preset を追加し既定化。3 値を receipt 化 |
| [#43](https://github.com/hjosugi/xalgo/issues/43) | [`77d431aabf`](https://github.com/xai-org/x-algorithm/commit/77d431aabf409ca1c1eed9bec7e2183f7c914e23)（9/30） | Phoenix two-tower immersive-only、ads head masking を data 側へ移動、visibility 再編 | scoring 既定値の変更なし。記録のみ |
| [#44](https://github.com/hjosugi/xalgo/issues/44) | [`b79b947ce9`](https://github.com/xai-org/x-algorithm/commit/b79b947ce9283c786822274ef8fe208c33c585b2)（10/1） | abuse-enforcement の restart-on-config-change、visibility の limited-actions copy / policy | scoring 既定値の変更なし。記録のみ |
| [#45](https://github.com/hjosugi/xalgo/issues/45) | [`76843a5eea`](https://github.com/xai-org/x-algorithm/commit/76843a5eea278ced444b21372d4e6d6909f5c35e)（10/2） | Home Mixer `SidSource` 追加、Phoenix proto の `ExcludedPostsBloomFilter` / `collected_actions`、visibility 再編 | scoring 既定値の変更なし。baseline の基準 commit に採用 |

7 件すべて「ranking に関係する変更」として正しく起票されていた。7 commit のうち
公開 scoring 既定値を動かしたのは 1 件（`a707cc27ba`）、scoring 実装の置き場所を
動かしたのは 1 件（`44d37ebf87`）で、残りは candidate source、Phoenix 学習・推論、
visibility-filtering、Grox / abuse-enforcement policy の変更である。

## 追跡の穴を塞ぐ

9/24 の抽出で scoring の本体が `xai-value-model/` と `vm-ranker/` へ移ったが、
`scripts/track_upstream.py` の `RANKING_PATHS` はこの 2 ディレクトリを監視して
いなかった。今回 `vm-ranker/` と `xai-value-model/` を追加し、回帰 corpus にも
`xai-value-model/scoring.rs`・`xai-value-model/weights.rs`・`vm-ranker/params.rs`・
`vm-ranker/scoring/value_model.rs` の 4 ケースを加えた（33 → 37 件）。

## xalgo 側の変更

- [`scripts/audit_model_contract.py`](../scripts/audit_model_contract.py):
  `source_2026_10` 世代を追加。`vm-ranker/params.rs` から 26 重みと設定を、
  `xai-value-model/scoring.rs` / `weights.rs` から normalization と offset 契約を、
  `home-mixer/scorers/value_model.rs` からローカル fallback の固定値を読む。
  9 月以前の `source_2026_08` と May demo も引き続き監査できる。
- [`state/model_contract_baseline.json`](../state/model_contract_baseline.json):
  `76843a5eea` で再記録（2026-10-03）。
- [`weights.json`](../weights.json): `upstream_2026_10` preset（source
  `76843a5eea`、introduced `a707cc27ba`）を追加し `default_preset` に設定。
  `upstream_2026_09` / `upstream_2026_08` は比較用として残す。
- [`scripts/track_upstream.py`](../scripts/track_upstream.py): `vm-ranker/` と
  `xai-value-model/` を監視対象に追加し、`_subsystem` も対応。
- [`state/upstream_tracking_corpus.json`](../state/upstream_tracking_corpus.json):
  value model の 4 パスを ranking ケースとして追加。
- 学習ラボ（`web/`）は 10 月 preset を既定にし、9 月 preset との差を説明に示す。

## 既存 analysis issue への影響

- [#1](https://github.com/hjosugi/xalgo/issues/1): 公開既定値が 9 月 → 10 月で
  動いた。snapshot から推定した重みの比較先は `upstream_2026_10` になる。
- [#6](https://github.com/hjosugi/xalgo/issues/6): VQV default は 0.0 のまま。
  click と click-dwell の重みが動いたので、VQV 探索の前提は再確認が必要。
- [#11](https://github.com/hjosugi/xalgo/issues/11): 実 cohort の author-disjoint
  viewer-feed 評価は今回も未実施。引き続き外部データが必要で、open のまま。

## 再現

```bash
nix develop
python scripts/audit_model_contract.py --ref 76843a5eea278ced444b21372d4e6d6909f5c35e
python scripts/audit_model_contract.py --ref main --json --fail-on-drift
python -m xalgo.cli score <URL> --preset upstream_2026_10 --json
python -m xalgo.cli score <URL> --preset upstream_2026_09 --json
```

9 月契約は `--ref 1b3fec20bc3fd9879bc3e9f3d9c42753cdc3fede --no-baseline` で、
8 月契約は `--ref d011592a1c8c4bfb23781ff15577a68dc08bdde1 --no-baseline` で、
5 月版契約は `--ref 0bfc2795d308f90032544322747caacd535f75ae --no-baseline` で
引き続き監査できる。
