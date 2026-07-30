# xalgo — X「おすすめ」スコア推定・上流追跡ツール

Version 0.1.1

[xai-org/x-algorithm](https://github.com/xai-org/x-algorithm) の
2026-05-15版（commit `0bfc2795d3`）を読み解き、投稿URLから公開カウントだけで
近似スコアを計算します。X APIのキー、Xログイン、Cookieは不要です。

> [!IMPORTANT]
> 実際の「おすすめ」順位や内部スコアを再現するものではありません。
> 本番の重みと閲覧者別Phoenix予測は非公開です。表示するのは
> `公開エンゲージメント数 ÷ views` を確率の代用にした研究用の近似値です。

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # requests のみ
```

## 使い方

### 1. ブラウザで学ぶ（学習ラボ）

**公開ページ:** https://hjosugi.github.io/xalgo/

```bash
python -m xalgo.web
# http://127.0.0.1:8000 を開く
```

投稿の公開カウントを手入力するか、Xの投稿URLから取得して、行動率・重み・
スコアへの寄与を画面で確認できます。候補取得からPhoenix予測、著者多様性までの
処理フローも図解しています。ログインやデータ保存はなく、手入力モードの計算は
ブラウザ内だけで完結します。

### 2. URL からスコア計算 (X API 不使用)

```bash
python -m xalgo.cli score "https://x.com/user/status/123456789"
python -m xalgo.cli score <URL> --preset legacy_2023 --json
python -m xalgo.cli score <URL> --dwell-p 0.3               # 非公開シグナルを仮定注入
python -m xalgo.cli score <URL> --preset full_template \
  --weight vqv=1.0 --vqv-p 0.1 \
  --vqv-min-duration-ms 10000                               # 動画感度分析
```

取得バックエンド（フォールバック順）: FxTwitter → VxTwitter →
X公式embed CDN（syndication）。X APIは使いませんが、各公開サービスの
可用性・仕様変更・レート制限の影響は受けます。

- **rate モード** (views あり): `p_hat = count/views` を式に代入。実物の
  「1インプレッションあたり行動確率」に対応する形。
- **raw モード** (views なし・2022年12月以前の投稿): log1p(count) の加重和。

### 3. 重みプリセット (weights.json)

| preset | 内容 |
|---|---|
| `repo_demo` | リポジトリ内に実在する唯一の公開数値 (run_pipeline.py) |
| `legacy_2023` | 2023年 twitter/the-algorithm の Heavy Ranker 重み (比較用) |
| `full_template` | 全22アクション網羅の編集用テンプレ |

本番重みはfeature switch注入で非公開です。逆推定の計画は
[`issues/001-weight-estimation.md`](issues/001-weight-estimation.md) を参照してください。

### 4. 公開モデル契約を約68KBで監査

```bash
python scripts/audit_model_contract.py
python scripts/audit_model_contract.py --ref main --json
python scripts/audit_model_contract.py --ref main --fail-on-drift
```

約2.9GBのPhoenix artifactを丸ごと落とさず、Git LFSのRange requestで内部configだけを
読みます。READMEとmodel実体、デモのaction indexと出力head順を比較できます。現在の
pinned releaseでは、root READMEの`256-dim/2-layer`に対しartifactは
`128-dim/4-layer`、デモのaction indexも`runners.py`の出力順と一致しません。
既知状態は[`state/model_contract_baseline.json`](state/model_contract_baseline.json)に固定し、
`--fail-on-drift`は既知不整合では失敗せず、LFS OID・model寸法・README・action順の
新しい変更だけをexit 1で通知します。

約3GBのartifactを実際に取得したfull inferenceでは、84,564候補からretrieval 200件、
ranking 200件を完走し、19列の確率分布を決定的に再生成できました。再現patch、receipt、
全列histogram、公開count proxyとの比較は
[`docs/phoenix-local-inference.md`](docs/phoenix-local-inference.md)を参照してください。
READMEの`~537K sports posts`に対し、配布corpus実体が84,564件という追加driftも記録しています。

### 5. 上流変更の自動検知

```bash
python -m xalgo.cli diff --since 2026-05-01
python scripts/track_upstream.py --evaluate-corpus --json
```

`.github/workflows/track-upstream.yml` は毎日06:00 JSTに実行されます。
`main` のcommitと、利用可能な場合はmerged PRの変更ファイルを調べ、ランキングに
関係する変更とGroxのspam/PTOS policy変更を区別してIssueを自動起票します。
上流は現在PR一覧REST APIを404にしていますが、その場合もcommit監視は継続します。
PR APIが公開された時点からファイル単位のPR検査とmerge commitの重複抑止が有効になります。
25件の人手分類コーパスでpath判定のprecision/recallを回帰検証できます。

### 6. 分析 issue の一括登録

```bash
./issues/create_issues.sh <owner/repo>   # gh CLIで10本を冪等に登録
```

001 重み逆推定 / 002 Phoenix mini ローカル推論 / 003 Author Diversity /
004 負シグナル / 005 取得信頼性 / 006 動画VQV / 007 追跡精度 /
008 action index契約 / 009 artifact-doc drift / 010 viewer別feed評価。

### 7. 実投稿での検証

```bash
python scripts/validate_popular.py            # 2026-07-20のスナップショット
cat urls.txt | python scripts/validate_popular.py --stdin
python scripts/validate_popular.py --json > result.json
```

実測結果と解釈は [`docs/validation-findings.md`](docs/validation-findings.md) を参照
してください。組み込み標本は第三者サイトXBeastの一時点のランキングであり、
母集団を代表する検証セットではありません。

### 8. 匿名化した実For You順位との比較

```bash
python scripts/evaluate_feed_snapshot.py examples/feed_snapshot.example.csv
python scripts/evaluate_feed_snapshot.py my-anonymized-feed.csv --k 5,10,20 --json
```

同一viewer・同一refresh内で、代理スコア順と実表示順のSpearman、Kendall tau-b、
NDCG@K、Top-K overlapを計算します。credential列を拒否し、入力SHA-256と層別結果も
出力します。CSV仕様と限界は
[`docs/feed-snapshot-evaluation.md`](docs/feed-snapshot-evaluation.md)を参照してください。

### 9. Author Diversityの感度分析

```bash
python scripts/simulate_author_diversity.py
python scripts/simulate_author_diversity.py \
  --author-scores 1.0,0.94,0.88 --competitor-scores 0.98,0.92,0.86 \
  --decays 0.5,0.7,0.9 --floors 0,0.2,0.4 --json
```

同一著者の複数候補を一つのfeed responseへ入れる`burst`と、responseを分けて
著者カウンタが毎回0へ戻る`distributed`を比較します。順位差に加え、n件目が
無補正時と同じスコアを保つために必要なbase score上昇率を出力します。
入力値は仮定であり、投稿間隔そのものの因果効果は示しません。

### 10. ネガティブシグナルの感度分析

```bash
python scripts/analyze_negative_signals.py \
  --unit-negative-weights --negative-scores-offset 0.1
python scripts/analyze_negative_signals.py --preset full_template \
  --weight not_interested=-1 --weight report=-10 \
  --negative-scores-offset 0.1 --json
```

上流`ranking_scorer.rs`のpositive/negative/total sumと`offset_score()`を再現し、
5種類の負シグナル確率をsweepします。本番の重みとoffsetは非公開なので、
`--unit-negative-weights`は無次元の仮定にすぎません。指定しない場合は
`weights.json`を使い、負重みがすべて0なら明示的なoverrideを要求します。

### 11. 動画 VQV 閾値の感度分析

```bash
python scripts/analyze_vqv_threshold.py \
  --durations-ms 2000,5000,10000,30000 \
  --thresholds-ms 0,5000,10000,30000 --vqv-p 0.1 --vqv-weight 1
python scripts/analyze_vqv_threshold.py \
  --snapshots examples/vqv_snapshots.example.csv --json
```

上流の厳密な`video_duration_ms > MIN_VIDEO_DURATION_MS`条件を、複数の閾値仮説で
sweepします。繰り返しsnapshot CSVを渡すと、動画長で分けたviews/hourも比較できます。
本番閾値・VQV重みは非公開で、公開view増加は露出後の観測値なので、差があっても本番閾値や
因果効果を特定したことにはなりません。詳細は
[`docs/sensitivity-analysis.md`](docs/sensitivity-analysis.md)を参照してください。

### 12. 取得バックエンドの監査

```bash
python scripts/audit_backends.py 123456789 987654321
cat urls.txt | python scripts/audit_backends.py --stdin --json > backend-audit.json
```

3バックエンドを個別に呼び、成功率、成功時レイテンシ、各カウントの取得率、
共通フィールドの相対差、標本内での推奨フォールバック順を出力します。

## テスト

```bash
python -m unittest discover -s tests -v
```

## ドキュメント

- [`docs/algorithm-deep-dive.md`](docs/algorithm-deep-dive.md) — アルゴリズム徹底解説
- [`docs/model-ai-ml-deep-dive.md`](docs/model-ai-ml-deep-dive.md) — AI/ML・Transformer・推薦モデル解説
- [`docs/external-analysis-review.md`](docs/external-analysis-review.md) — 外部記事・GitHub repo・論文の比較検証
- [`docs/model-validation-plan.md`](docs/model-validation-plan.md) — モデルと実投稿を検証する実験計画
- [`docs/feed-snapshot-evaluation.md`](docs/feed-snapshot-evaluation.md) — 匿名化For You順位の評価方法
- [`docs/validation-findings.md`](docs/validation-findings.md) — 実測検証レポート
- [`docs/backend-audit.md`](docs/backend-audit.md) — 取得先の成功率・欠損・数値差
- [`docs/sensitivity-analysis.md`](docs/sensitivity-analysis.md) — Author Diversity・VQV・負シグナル感度分析
- [`docs/upstream-tracking-evaluation.md`](docs/upstream-tracking-evaluation.md) — 追跡精度・構造差分・重複抑止

## 免責

出力は公開エンゲージメントに基づく**群集平均の近似**であり、
実際のFor Youスコア（閲覧者ごとのPhoenix予測）ではありません。
研究・教育目的で利用し、Xおよび取得先サービスの利用条件を確認してください。

Apache-2.0 License。本プロジェクトはX Corp. / xAIの公式ツールではありません。
