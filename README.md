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
  --weight vqv=1.0 --vqv-p 0.1                              # 動画感度分析
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
./issues/create_issues.sh <owner/repo>   # gh CLIで7本を冪等に登録
```

001 重み逆推定 / 002 Phoenix mini ローカル推論 / 003 Author Diversity /
004 負シグナル / 005 取得信頼性 / 006 動画VQV / 007 追跡精度。

### 6. 実投稿での検証

```bash
python scripts/validate_popular.py            # 2026-07-20のスナップショット
cat urls.txt | python scripts/validate_popular.py --stdin
python scripts/validate_popular.py --json > result.json
```

実測結果と解釈は [`docs/validation-findings.md`](docs/validation-findings.md) を参照
してください。組み込み標本は第三者サイトXBeastの一時点のランキングであり、
母集団を代表する検証セットではありません。

## テスト

```bash
python -m unittest discover -s tests -v
```

## ドキュメント

- [`docs/algorithm-deep-dive.md`](docs/algorithm-deep-dive.md) — アルゴリズム徹底解説
- [`docs/validation-findings.md`](docs/validation-findings.md) — 実測検証レポート

## 免責

出力は公開エンゲージメントに基づく**群集平均の近似**であり、
実際のFor Youスコア（閲覧者ごとのPhoenix予測）ではありません。
研究・教育目的で利用し、Xおよび取得先サービスの利用条件を確認してください。

Apache-2.0 License。本プロジェクトはX Corp. / xAIの公式ツールではありません。
