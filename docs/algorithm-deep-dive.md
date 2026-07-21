# xai-org/x-algorithm 徹底解説

対象は2026-05-15版、commit
[`0bfc2795d3`](https://github.com/xai-org/x-algorithm/tree/0bfc2795d308f90032544322747caacd535f75ae)
（Apache-2.0）。ここでは次のラベルを使う。

- **確認済み**: 公開コードまたは配布モデルの設定から直接確認できる
- **推論**: 公開情報から合理的に推測できるが、学習データや本番設定がない
- **不明**: 公開物だけでは判定できない

## 結論

XのFor Youは「投稿に一つの人気点を付ける」仕組みではない。閲覧者ごとに、各候補へ
「いいね・返信・クリック・滞在・否定反応などを起こす確率」をPhoenixが予測し、
Home Mixerが非公開の重みで合成し、著者多様性・ネットワーク内外補正・安全性フィルタを
適用する。したがって同じ投稿でも、閲覧者、時刻、候補集合、実験設定によって順位は変わる。

公開Pythonモデルで重要なのは、投稿本文をLLMへ渡して意味を直接採点しているわけでは
ない点である。入力は主にユーザー・投稿・著者IDのハッシュ埋め込み、行動履歴、表示面、
投稿時刻である。`tweet_text` はHome Mixerで保持されるが、公開
[`RecsysBatch`](https://github.com/xai-org/x-algorithm/blob/0bfc2795d308f90032544322747caacd535f75ae/phoenix/recsys_model.py#L126)
には本文フィールドがない。

## 全体パイプライン

| コンポーネント | 役割 | 公開状態 |
|---|---|---|
| `home-mixer` | 候補取得・hydrate・filter・score・selectを調停 | アーキテクチャ中心。内部crate、proto、設定値の欠落あり |
| `thunder` | フォロー中の新着投稿を実時間取得 | Rustコードあり |
| `phoenix` | Two-Tower retrievalとTransformer ranking | JAXコードと凍結済みminiモデルあり |
| `grox` | スパム、カテゴリ、PTOS等のコンテンツ理解 | ランキング本体とは別系統 |
| `candidate-pipeline` | Source/Hydrator/Filter/Scorer等の枠組み | 一部は内部依存 |

概略は次の通り。

```text
viewer context + recent actions
  ├─ Thunder: in-network candidates
  └─ Phoenix Retrieval: out-of-network candidates
          ↓
hydrate metadata → pre-filter → Phoenix action prediction
          ↓
weighted sum → normalization → author diversity → OON adjustment
          ↓
top-K selection → visibility/conversation filtering → feed
```

「公開リポジトリをcloneすれば本番For Youサーバー全体を再現できる」という意味ではない。
Rust側には`xai_feature_switches`、予測クライアント、proto、`normalize_score`など公開
スナップショット外の依存がある。一方、PhoenixのPythonデモは約2.9GBの配布物を取得すれば
retrieval→rankingを実行できる。

## Phoenix Retrieval: 数百万件から候補を絞る

Phoenixは典型的な**二段推薦**である。最初のretrievalはTwo-Towerを使う。

```text
u = normalize(UserTransformer(user_id, action_history))
v_i = normalize(MLP(post_id_embedding_i || author_id_embedding_i))
s_retrieval(i) = u · v_i
```

- User Towerはユーザーと履歴をTransformerで符号化し、平均pooling後にL2正規化する。
- Candidate Towerは投稿と著者の埋め込みを連結し、2層MLP（SiLU）で同じ空間へ射影する。
- 両方を正規化するため、内積はcosine similarityに等しい。
- 候補側ベクトルを事前計算でき、ANNや行列積で高速に上位K件を取れる。

公開デモではスポーツ投稿約537K件の事前計算済みcorpusに対して
[`corpus_repr @ user_repr`](https://github.com/xai-org/x-algorithm/blob/0bfc2795d308f90032544322747caacd535f75ae/phoenix/run_pipeline.py#L302)
を実行し、上位200件をrankerへ渡す。これは全X投稿を対象とした本番corpusではない。

## Phoenix Ranking: 閲覧者別の行動確率を出す

mini checkpointの実設定は次の通り。これはREADMEの転記ではなく、Git LFSの
`ranker/config.json`と`retrieval/config.json`をRange readして確認した値である。

| 設定 | 値 |
|---|---:|
| 埋め込み次元 `D` | 128 |
| Transformer層 | 4 |
| attention heads | 4 |
| head key size | 32 |
| 履歴長 | 127 |
| 一度にrankする候補 | 64 |
| 離散action logits | 19 |
| user/item/author vocabulary | 各1,000,000 |
| user/item/author hashes | 各2 |
| product surface vocabulary | 16 |
| 投稿age bucket幅 | 60分 |

最大token列は`1 user + 127 history + 64 candidates = 192`、形は概ね
`[batch, 192, 128]`となる。各履歴tokenは投稿・著者・行動・product surface等を合成し、
候補tokenは投稿・著者・product surface・投稿age等を合成する。

### Candidate isolation

候補`c_i`はuser/historyと自分自身へattentionできるが、他候補`c_j`へはattention
できない。公開実装の
[`make_recsys_attn_mask`](https://github.com/xai-org/x-algorithm/blob/0bfc2795d308f90032544322747caacd535f75ae/phoenix/grok.py#L39)
が候補ブロックを対角要素だけにする。

これにより、同じ候補の予測が「同じバッチにどの候補を詰めたか」で変わりにくく、候補を
独立に並列採点できる。ただし最終順位は後段の多様性やフィルタで候補集合に依存する。

### Multi-task出力

各候補の表現`h_i`をactionごとの列へ射影する。

```text
z_i,a = h_i · W_a                 # logit
p_i,a = sigmoid(z_i,a)            # action probability
score_i = Σ_a w_a p_i,a           # Home Mixerで合成
```

`runners.py`が列挙する19出力は favorite, reply, repost, photo expand, click,
profile click, VQV, share, DM share, copy-link share, dwell, quote, quoted click,
follow author, not interested, block, mute, report, dwell time である。別に8列の
continuous prediction定義もあり、dwell time、video watch time、scroll depth等を含む。

Home Mixerの
[`ranking_scorer.rs`](https://github.com/xai-org/x-algorithm/blob/0bfc2795d308f90032544322747caacd535f75ae/home-mixer/scorers/ranking_scorer.rs#L12)
は22信号を扱う。Pythonデモ19列、continuous 8列、本番調停層22信号は同一の集合では
ない。この差を無視して「Phoenixは19シグナル」と断定しない方がよい。

## Grok系とは何か

PhoenixはGrok-1のTransformer実装を推薦向けに移植しており、RMSNorm、RoPE、
multi-head attention、gated feed-forward blockを使う。しかしGrok-1そのものは
314B parameter、64層、SentencePiece語彙を持つMoE言語モデルであり、mini Phoenixとは
サイズも入力も出力も目的関数も異なる。

| | Grok-1 LLM | Phoenix mini |
|---|---|---|
| token | テキストtoken | user/history/candidate埋め込み |
| 目的 | 次token予測・生成 | 候補取得と複数行動予測 |
| 出力 | 語彙logits | action logits / continuous values |
| 公開仕様 | 314B、64層、MoE | D=128、4層、dense Transformer |

したがって「Grokが投稿内容を読んで思想や文章品質を直接採点している」は、公開Phoenix
コードからは確認できない。Grox等が作るカテゴリや埋め込みが別経路で使われる可能性はあるが、
公開rankerの直接入力として本文tokenは示されていない。

より詳しい用語・テンソル・学習と推論の違いは
[`model-ai-ml-deep-dive.md`](model-ai-ml-deep-dive.md)を参照。

## ハッシュ埋め込みが意味すること

巨大な64-bit IDごとに無制限の表を作る代わりに、user/item/authorをそれぞれ2本の
hashで各100万bucketへ写し、複数埋め込みを射影して使う。

- 長所: 語彙表が固定サイズになり、未知IDにも必ず表引きできる。
- 短所: 異なるIDが同じbucketへ衝突する。2本のhashは衝突の曖昧さを減らすが消さない。
- 注意: post ID embeddingは本文の意味ベクトルとは限らない。公開学習コードと学習データが
  ないため、何をどの程度encodeしたかは断定できない。

## 重み・補正・フィルタ

Home Mixerは22予測を`Σ weight × prediction`で合成するが、重みは
`xai_feature_switches::Params`から実行時に読み込まれ、数値は公開されていない。
VQV/quoted VQVには動画長条件があり、その閾値も非公開である。

合成後は次が適用される。

1. `normalize_score`: 呼び出しはあるが実装は公開スナップショットにない。
2. author diversity: 同一著者のn件目へ`(1-floor) × decay^n + floor`を乗算。
3. OON補正: out-of-network候補へ状況別係数を乗算。係数値は非公開。
4. visibility、既視聴、重複、会話dedup、ブロック・ミュート等のfilter。

## 公開物にある二つの不整合

### 1. READMEとartifact config

root READMEはmini modelを`256-dim / 2 layers`と説明するが、Phoenix READMEは
`128-dim / 4 layers`と説明する。配布ZIP内のretrieval/ranker configは両方とも
`128 / 4`である。本リポジトリは**artifactを実行時の正**として扱う。

### 2. デモのaction index

`run_pipeline.py`はserver側のaction enum値として`FAV=1, REPLY=4, RT=6,
DWELL=11`等を定義し、それをそのまま`all_probs[:, index]`へ使う。一方、
`runners.py::ACTIONS`で出力0始まりの列1はreply、4はclick、6はVQV、11はquoteである。
つまり公開ファイル同士を素直に読むと、デモのラベルと実際に加重されるheadが一致しない。

これは**公開デモの契約不整合**であり、本番モデルの不具合だとは断定できない。artifact内に
head名metadataがないため、正しい順序を上流へ確認する必要がある。本ツールの
`repo_demo`も「ラベルどおりなら」という感度分析プリセットとして扱い、正解値とは呼ばない。

```bash
python scripts/audit_model_contract.py
python scripts/audit_model_contract.py --ref main --json
python scripts/audit_model_contract.py --ref main --strict  # 不整合時 exit 1
```

この監査は2.9GB全体を取得せず、約68KBのRange requestだけでモデル設定を検査する。

## 2023版との比較

| | 2023 `twitter/the-algorithm` | 2026 `xai-org/x-algorithm` |
|---|---|---|
| 主ランカー | parallel MaskNet Heavy Ranker | Phoenix Transformer |
| 入力 | 多数の手作り特徴量 | ID/author/action履歴中心 |
| 候補取得 | Earlybird、UTEG、SimClusters等 | Thunder + Phoenix Two-Tower等 |
| 公開重み | 2023-04-05時点値を companion ML repoで公開 | 本番値は非公開 |
| 公開学習 | random dataで学習可能 | 学習pipeline/loss/dataは非公開、推論checkpointのみ |

有名な`reply=13.5`、`report=-369`は
[`twitter/the-algorithm-ml`](https://github.com/twitter/the-algorithm-ml/blob/b85210863f7a94efded0ef5c5ccf4ff42767876c/projects/home/recap/README.md)
に記載された**2023-04-05時点の旧Heavy Ranker**値である。2026 Phoenixへ流用する根拠はない。
また重みの大きさだけでは寄与を比較できず、`weight × predicted probability`の分布が必要である。

## xalgoのURLスコアとの境界

xalgoは公開countを使い、`count / views`をaction probabilityの代理にする。これは
Phoenixがserving時に出した閲覧者別予測ではなく、表示後に起きた結果の全期間・全閲覧者平均で
ある。本文、閲覧者履歴、候補集合、非公開signal、重み、正規化、filterを欠く。

したがって用途は「仮定した重みに対する感度分析」と「公開指標の定点観測」であり、実際の
For You順位を再現したという主張には使えない。妥当な検証設計は
[`model-validation-plan.md`](model-validation-plan.md)、実投稿の既存観測は
[`validation-findings.md`](validation-findings.md)を参照。
