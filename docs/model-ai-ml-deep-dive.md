# Phoenixを理解するためのAI・ML・推薦モデル解説

## まず用語を分ける

| 用語 | このリポジトリでの意味 |
|---|---|
| AI | 推薦・生成・分類などを含む広い総称 |
| ML | データからパラメータを学ぶ手法。Phoenixはここに属する |
| Deep Learning | 多層ニューラルネットを使うML。Phoenix/Grokとも該当 |
| モデル | 入力を出力へ写す関数と構造 |
| パラメータ | 学習で得た埋め込み表や行列の数値 |
| checkpoint | ある時点のパラメータを保存したもの |
| inference | checkpointを使って予測する処理 |
| training | 正解ラベルとの誤差を減らすようパラメータを更新する処理 |

Phoenix公開物には**推論コードと凍結checkpoint**がある。一方、実データ、loss構成、
negative sampling、optimizer、継続学習pipelineは公開されていない。よってモデルを動かす
ことはできても、本番と同じ方法で再学習できるとは限らない。

## 推薦は分類ではなく「検索 + 予測 + 意思決定」

推薦系は一つのモデルだけでは完結しない。

1. **Retrieval**: 数百万以上の投稿から候補を数百～数千へ減らす。
2. **Ranking**: 各候補について閲覧者が行動する確率を細かく予測する。
3. **Objective aggregation**: いいね、返信、滞在、否定反応等を重み付き合成する。
4. **Re-ranking/policy**: 多様性、安全性、既視聴、ネットワーク内外等を調整する。

これはYouTubeのcandidate generation→rankingという古典的な二段構成と同型であり、
大規模推薦で計算量と表現力を両立する標準パターンである。

## Embedding

IDは64-bit整数のままでは「似ている・似ていない」を計算しにくい。embedding tableは
IDを`D=128`個の浮動小数点へ変換する。

```text
post_id --hash--> bucket_a, bucket_b --lookup--> e_a, e_b --projection--> e_post
```

学習が十分なら、同じ閲覧パターンを持つ投稿や著者が近い表現を獲得しうる。ただしこれは
**推論**であり、公開releaseは学習データや目的関数を示していない。本文を直接tokenizeした
semantic embeddingとは別物である。

## Transformerが履歴を処理する仕組み

各履歴位置には、どの投稿・著者に対してどの行動をし、どのsurfaceで見たかを埋め込んだ
ベクトルが入る。self-attentionは各位置から他位置を参照し、「最近のスポーツ動画への滞在」の
ような組み合わせを固定長のuser representationへ反映できる。

PhoenixのTransformer部はGrok-1由来で、主に次を使う。

- **RoPE**: 順序をattentionへ入れる。Phoenixは新しい履歴を固定位置へ右寄せする。
- **RMSNorm**: ベクトルのスケールを整え学習・推論を安定させる。
- **Multi-head attention**: 異なる関係を複数headで並行して捉える。
- **Gated FFN**: tokenごとの非線形変換を行う。
- **Residual connection**: 入力情報を保ちながら更新を積み重ねる。

「Grok-based」は部品の系譜を表す。Grok-1はテキストtokenから次tokenを予測するMoE LLM、
Phoenixは行動sequenceから候補への反応を予測するdense推薦モデルである。

## Logit・sigmoid・確率

モデルの生出力`z`はlogitと呼ばれ、任意の実数を取る。sigmoidで0～1へ変換する。

```text
p = 1 / (1 + exp(-z))
```

ただし数値が0.8だから現実に必ず80%発生するとは限らない。確率として読むには
calibration検証が必要である。またクリック、返信、滞在は互いに排他的ではないため、19列へ
softmaxをかけて合計1にするのではなく、各headを独立にsigmoid化する設計が自然である。

## Multi-task learning

一つの共有Transformerから複数のaction headを同時に出す。共有表現はデータを効率よく使える
一方、頻度も意味も違うtaskが干渉することがある。一般にはtask別loss weightやsamplingが
重要だが、Phoenix公開releaseには学習lossが含まれないため、次は不明である。

- 各actionのpositive/negative label定義
- actionごとのloss weight
- class imbalance対策
- retrieval lossとnegative sampling
- calibration方法
- production checkpointの更新頻度・サイズ

なおGoogleのMMoEはtask間の共有量をgateで変える別方式である。Home Mixerに
`PhoenixMOESource`という名前はあるが、公開mini rankerの`grok.py`はGrok-1の8-expert MoEを
そのまま搭載したモデルではない。

## 「内容の質」はどこに入るか

公開Phoenixが直接見るのはID・著者・履歴・contextなので、本文の意味は少なくとも次の間接経路
で表現されうる。

- 過去にどのユーザーがそのpost/authorへどう反応したかを学習したID embedding
- Grox等が生成した分類・topic・safety情報を候補取得やfilterで利用
- 投稿の鮮度、product surface、動画・media等のhydrated metadataを後段で利用

しかし「キーワードを増やせばembeddingが鋭くなる」「特定の文体をGrokが高評価する」といった
具体的SEO規則は、公開rankerコードからは導けない。未知の新規投稿は行動データが乏しいため、
本番にはcold-start用の追加表現がある可能性が高いが、これは公開物だけでは不明である。

## モデルの数値と最終スコアは別物

Phoenixが予測するのは`P(action | viewer, history, candidate, context)`であり、Home Mixerが
その後にbusiness objectiveを反映した重み付き和を作る。

```text
prediction model:  viewer + candidate -> probability vector
policy/objective:  probability vector -> weighted score
feed system:       score + constraints -> displayed order
```

モデルを完全に再現しても、非公開重み・filter・候補集合がなければ最終フィードは再現できない。
逆に公開countから重みを推定する場合も、表示順位によるexposure biasと、表示されたものだけを
観測するselection biasを分離しなければならない。

## 関連する代表研究との位置づけ

| 研究/実装 | 共通点 | Phoenixとの差 |
|---|---|---|
| YouTube DNN recommender | candidate generationとrankingの二段構成 | 特徴・モデルは別 |
| SASRec | self-attentionで行動sequenceを推薦へ使う | SASRecは次item予測中心 |
| BERT4Rec | Transformerによるsequential recommendation | bidirectional masked-item学習。Phoenix lossは非公開 |
| Pinterest TransAct | realtime user action sequenceをTransformerで扱う | productionの特徴構成・目的が別 |
| MMoE | 複数taskを同時に最適化 | 公開Phoenixは単純にMMoEとは確認できない |

一次資料へのリンクと二次記事の検証は
[`external-analysis-review.md`](external-analysis-review.md)にまとめた。
