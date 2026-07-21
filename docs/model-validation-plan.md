# Phoenix・代理スコア検証計画

## 何を検証するかを分離する

「アルゴリズムと合っているか」は一つの問いではない。

| レベル | 問い | 現在可能か |
|---|---|---|
| L0 Contract | 公開README・code・artifactが内部整合するか | 可能 |
| L1 Reproduction | 公開checkpointが同入力で同出力を返すか | 可能 |
| L2 Proxy | 公開count代理スコアが将来engagementと関連するか | 条件付きで可能 |
| L3 Feed | 特定viewerの実For You順位と予測順位が一致するか | feed snapshotがあれば部分的 |
| L4 Causal | score変更が露出を増やしたか | randomization/A-Bなしでは原則不可 |

## L0: 公開契約の監査

```bash
python scripts/audit_model_contract.py --ref 0bfc2795d3
python scripts/audit_model_contract.py --ref main --strict
```

検査項目:

- root READMEとPhoenix READMEのmodel size
- artifact内retrieval/ranker config
- `run_pipeline.py`のindexと`runners.py::ACTIONS`の出力順
- history/candidate長、action数、hash数の変更

現時点ではmodel sizeとaction indexに不整合がある。CIで`--strict`を直ちに必須化すると上流の
既知不整合で常時失敗するため、まずbaseline JSONを保存し「新しい差分」だけを警告する設計が
よい。

## L1: 公開checkpointの再現性

同じcommit、LFS SHA-256、config、input、runtime versions、random seed、device、outputを
manifest化する。CPU/GPU・JAX backendで浮動小数点差がありうるため、完全一致hashと
許容誤差内の数値一致を分ける。

推奨テスト:

1. 同一環境でのrepeatability。
2. CPUとGPUでtop-K overlap、Kendall/Spearman順位相関。
3. candidate batchを並べ替えても各候補scoreが不変か。
4. padding候補数を変えても実候補scoreが不変か。
5. 履歴を1actionずつ変えるablation。
6. hash collisionを意図的に作った入力で感度を測る。

`x-algorithm-receipts`のような署名receiptはL1の証跡に有用だが、L3/L4の証明にはならない。

## L2: 公開count代理スコア

人気投稿だけを事後に集めるとselection biasが生じる。投稿時点で層化標本を登録し、同じURLを
時系列で観測する。

推奨スキーマ:

```text
post_id, author_id_hash, observed_at, post_age_minutes,
views, likes, replies, reposts, quotes, bookmarks?,
media_type, follower_bucket, language, sampling_stratum,
proxy_score, fetch_backend, fetch_status
```

観測窓は投稿後15分、30分、1h、2h、6h、24h、72hを基本にする。各時点で利用できた情報だけで
将来6h/24hの増分を予測し、未来countを特徴へ混ぜない。

### 指標

- 連続値: Spearman ρ、Kendall τ、MAE（log views）
- 上位選別: Precision@K、Recall@K、NDCG@K
- 二値action確率: log loss、Brier score、reliability diagram、ECE
- 増幅: `future views / current views`または時間当たり増分。ただし0除算と小標本を処理
- 不確実性: author単位cluster bootstrapで95% CI

比較baselineは最低でも「現在viewsのみ」「投稿ageのみ」「author過去中央値」「単純engagement
rate」を含める。複雑なscoreがこれらをout-of-sampleで上回らなければ改善とはいえない。

## L3: 閲覧者別feed snapshot

Phoenixはpersonalizedなので、直接検証に最も近い単位は
`(viewer pseudonym, request time, candidate set, displayed position)`である。

- 同一viewer、同一snapshot内で順位比較する。
- refreshごとの候補集合変更を別requestとして扱う。
- 広告、Who to Follow、会話注入等をpost候補と混ぜない。
- network内外、既視聴、著者重複、media typeで層別する。
- 個人データはhash化し、cookie/tokenを保存しない。

候補集合に入らなかった投稿の順位は観測できない。表示された投稿だけの評価にはposition biasと
exposure biasがあるため、「高順位だからengagementされた」の逆因果を除けない。

## L4: 因果検証

本当に「この変更が配信を増やした」と言うには、randomized exposure、interleaving、A/B test、
またはlogging propensityを使ったoff-policy evaluationが必要である。単純な公開count相関では
代替できない。

[Unbiased Learning-to-Rank with Biased Feedback](https://www.ijcai.org/proceedings/2018/738)
が示すように、暗黙feedbackにはposition biasが入る。IPS等は表示確率propensityが既知または
推定可能な場合に有効だが、公開X観測では通常その値がない。したがって本プロジェクトはL2/L3の
結果を観測的関連として報告し、因果効果とは表現しない。

## 合格基準の例

- 事前登録した4週間以上のtemporal holdoutでbaselineを上回る。
- 同一authorがtrain/testへ漏れる評価と、author-disjoint評価を両方示す。
- `n`、欠損率、backend失敗率、CIを必ず併記する。
- 係数・閾値をtest setを見て調整しない。
- 反証例（高proxy/低増幅、低proxy/高増幅）を個別に調べる。
- 結果を再生成するinput snapshot、commit、設定を保存する。

## 次に実装する分析

1. URL cohortの定点観測collectorと匿名化schema。
2. temporal splitを備えた評価notebook/CLI。
3. L0監査結果のbaseline差分をupstream追跡Issueへ統合。
4. 公開Phoenix artifactのdeterministic receipt生成。
5. viewer自身が提供したfeed snapshotとのNDCG比較。
