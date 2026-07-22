# xalgo — X「おすすめ」スコア推定・上流追跡ツール

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

### 1. URL からスコア計算 (X API 不使用)

```bash
python -m xalgo.cli score "https://x.com/user/status/123456789"
python -m xalgo.cli score <URL> --preset legacy_2023 --json
python -m xalgo.cli score <URL> --dwell-p 0.3               # 非公開シグナルを仮定注入
python -m xalgo.cli score <URL> --preset full_template \
  --weight vqv=1.0 --vqv-p 0.1                              # 動画感度分析
```

取得バックエンド（フォールバック順）: FxTwitter → VxTwitter →
X公式embed CDN（syndication）。X APIは使いませんが、各公開サービスの
可用性・仕様変更・レート制限の影響は受けます。

- **rate モード** (views あり): `p_hat = count/views` を式に代入。実物の
  「1インプレッションあたり行動確率」に対応する形。
- **raw モード** (views なし・2022年12月以前の投稿): log1p(count) の加重和。

### 2. 重みプリセット (weights.json)

| preset | 内容 |
|---|---|
| `repo_demo` | 2026 `run_pipeline.py`に書かれたラベル上のデモ値。出力indexに既知の不整合あり |
| `legacy_2023` | 2023-04-05 `twitter/the-algorithm-ml` Heavy Ranker重み（歴史比較専用） |
| `full_template` | 全22アクション網羅の編集用テンプレ |

本番重みはfeature switch注入で非公開です。逆推定の計画は
[`issues/001-weight-estimation.md`](issues/001-weight-estimation.md) を参照してください。

### 3. 公開モデル契約を約68KBで監査

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

### 4. 上流変更の自動検知

```bash
python -m xalgo.cli diff --since 2026-05-01
```

`.github/workflows/track-upstream.yml` は毎日06:00 JSTに実行されます。
`main` のcommitと、利用可能な場合はmerged PRの変更ファイルを調べ、ランキングに
関係する変更があればIssueを自動起票します。上流は現在PR一覧REST APIを404に
していますが、その場合もcommit監視は継続し、PR APIが公開された時点から
ファイル単位のPR検査が自動で有効になります。

### 5. 分析 issue の一括登録

```bash
./issues/create_issues.sh <owner/repo>   # gh CLIで10本を冪等に登録
```

001 重み逆推定 / 002 Phoenix mini ローカル推論 / 003 Author Diversity /
004 負シグナル / 005 取得信頼性 / 006 動画VQV / 007 追跡精度 /
008 action index契約 / 009 artifact-doc drift / 010 viewer別feed評価。

### 6. 実投稿での検証

```bash
python scripts/validate_popular.py            # 2026-07-20のスナップショット
cat urls.txt | python scripts/validate_popular.py --stdin
python scripts/validate_popular.py --json > result.json
```

実測結果と解釈は [`docs/validation-findings.md`](docs/validation-findings.md) を参照
してください。組み込み標本は第三者サイトXBeastの一時点のランキングであり、
母集団を代表する検証セットではありません。

### 7. 匿名化した実For You順位との比較

```bash
python scripts/evaluate_feed_snapshot.py examples/feed_snapshot.example.csv
python scripts/evaluate_feed_snapshot.py my-anonymized-feed.csv --k 5,10,20 --json
```

同一viewer・同一refresh内で、代理スコア順と実表示順のSpearman、Kendall tau-b、
NDCG@K、Top-K overlapを計算します。credential列を拒否し、入力SHA-256と層別結果も
出力します。CSV仕様と限界は
[`docs/feed-snapshot-evaluation.md`](docs/feed-snapshot-evaluation.md)を参照してください。

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

## 免責

出力は公開エンゲージメントに基づく**群集平均の近似**であり、
実際のFor Youスコア（閲覧者ごとのPhoenix予測）ではありません。
研究・教育目的で利用し、Xおよび取得先サービスの利用条件を確認してください。

Apache-2.0 License。本プロジェクトはX Corp. / xAIの公式ツールではありません。
