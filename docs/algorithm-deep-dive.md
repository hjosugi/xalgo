# xai-org/x-algorithm 徹底解説

対象: 2026-05-15リリース版、commit
[`0bfc2795d3`](https://github.com/xai-org/x-algorithm/commit/0bfc2795d308f90032544322747caacd535f75ae)
（Apache-2.0）。以下は公開コードから確認できる範囲と、そこからの推論を分けて記述する。

## 全体像

For You フィードは5コンポーネントで構成される:

| コンポーネント | 言語 | 役割 |
|---|---|---|
| **home-mixer** | Rust | オーケストレーション。gRPC `ScoredPostsService` |
| **thunder** | Rust | in-network (フォロー中) 投稿のインメモリストア。Kafka 実時間取り込み |
| **phoenix** | Python/JAX | ML 本体。Grok-1 移植の Transformer。retrieval + ranking |
| **grox** | Python | コンテンツ理解 (スパム分類・カテゴリ分類・PTOS 執行) |
| **candidate-pipeline** | Rust | Source/Hydrator/Filter/Scorer/Selector/SideEffect のトレイト枠組み |

処理フロー: Query Hydration (行動履歴・フォローリスト・impression bloom filter 等)
→ 候補取得 (Thunder + Phoenix Retrieval) → Hydration → Pre-Scoring Filters
→ Scoring → Selection (top-K) → Post-Selection Filters (VF/会話dedup)。

## 設計思想: 手作り特徴量の全廃

2023年版 (twitter/the-algorithm) は SimClusters, TwHIN, Real Graph など
大量の手作り特徴量 + LightGBM系だった。2026年版は **ユーザーの行動履歴
シーケンスを Grok ベース Transformer に入れるだけ**。特徴量エンジニアリングを
消し、データパイプラインを簡素化した。埋め込みはIDの**多重ハッシュ**
(user/item/author 各2本, recsys_model.py) で語彙爆発を回避する。

## Phoenix: 2段構成

### Retrieval (Two-Tower)
- User Tower: 行動履歴を Transformer で符号化 → 正規化埋め込み [B, D]
- Candidate Tower: 全投稿の埋め込み [N, D]
- 内積 ANN で数百万 → 数百件

### Ranking (Candidate Isolation)
- 入力: ユーザー文脈 + 候補投稿群
- **候補同士は attention できない** マスク → スコアがバッチ構成に依存せず、
  キャッシュ可能・一貫
- 出力: 行動ごとの logit → sigmoid で確率

予測アクション (phoenix/runners.py ACTIONS, 19種):
favorite, reply, repost, photo_expand, click, profile_click, vqv,
share, share_via_dm, share_via_copy_link, dwell, quote, quoted_click,
follow_author, **not_interested, block_author, mute_author, report** (負),
dwell_time (連続値)。

公開チェックポイントは mini 版 (256-dim / 4 heads / 2 layers, 約3GB LFS)。
本番は継続学習中のより大きいモデルのスナップショット。

## スコア式 (home-mixer/scorers/ranking_scorer.rs)

```
combined = Σ weight_i × P(action_i)
offset_score = combined + NEGATIVE_SCORES_OFFSET               (combined ≥ 0)
             = (combined + negative_sum) / total_sum × OFFSET  (combined < 0)
normalized   = normalize_score(candidate, offset_score)
```

重要な事実: **重みの実数値はリポジトリに存在しない**。
`xai_feature_switches::Params` で実行時注入され、非公開。
コード内に実在する唯一の数値は phoenix/run_pipeline.py のデモ値:
`fav 1.0 / reply 0.5 / rt 0.3 / dwell 0.2` (本ツールの `repo_demo` プリセット)。

条件付き重み:
- **VQV** (video quality view): `video_duration_ms > MIN_VIDEO_DURATION_MS`
  のときのみ有効 (閾値も非公開)
- quoted_vqv も同様の duration チェックあり

## スコア後の補正

`normalize_score` の実装はこの公開スナップショットに含まれていないため、
本ツールはこの正規化を再現しない。

1. **AuthorDiversityScorer**: 生の加重スコア順に同一著者の n 番目の投稿へ
   `(1-floor)·decay^n + floor` を乗算。連投を減衰。
2. **OONScorer**: out-of-network 候補に `OON_WEIGHT_FACTOR` を乗算
   (in-network 優遇)。

## フィルタ

Pre-Scoring: 重複 / 古い投稿 / 自分の投稿 / ブロック・ミュート著者 /
ミュートキーワード / 既視聴 (impression bloom filter) / 購読不可コンテンツ。
Post-Selection: VFFilter (削除・スパム・暴力等) / 会話スレッド dedup。

## Grox

分類器 (スパム, カテゴリ, PTOS)・埋め込み・タスク実行エンジン。
Grok を使ったコンテンツ理解のバッチ/ストリーム基盤。ランキング本体では
なくポリシー執行・メタデータ生成側。

## 2023年版との対比 (要点)

| | 2023 (the-algorithm) | 2026 (x-algorithm) |
|---|---|---|
| ランカー | Heavy Ranker (MaskNet) | Phoenix (Grok系 Transformer) |
| 特徴量 | 数千の手作り特徴量 | 行動履歴シーケンスのみ |
| 重み | README に公開 (reply 13.5, report -369 等) | 非公開 (feature switch) |
| 候補取得 | Earlybird / UTEG / SimClusters等 | Thunder + Two-Tower ANN |

## 本ツールの近似との対応

実物: `P(action)` は視聴者ごとの Phoenix 予測。
本ツール: 公開カウント ÷ views の**経験レート**で代用（rateモード）。
閲覧者履歴、非公開アクション、内部重み、`normalize_score`、候補集合、フィルタを
再現できないため、値の絶対比較や実フィード順位の断定には使えない。
差分と限界は [`validation-findings.md`](validation-findings.md) を参照。
