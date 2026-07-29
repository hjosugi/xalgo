# 匿名化For You feed snapshot評価

## 目的と境界

`evaluate_feed_snapshot.py`は、実際に表示された順序とxalgo代理スコア順を**同じ閲覧者・同じ
refresh内**で比較する。Xへログインせず、X API、cookie、tokenを使わない。自動取得機能も
持たず、ユーザーが安全に匿名化したCSVだけを読む。

これはPhoenixの完全再現でも因果検証でもない。表示された候補だけを観測するため、候補に
入らなかった投稿、position bias、exposure bias、selection biasを除去できない。

## 入力CSV

サンプル: [`examples/feed_snapshot.example.csv`](../examples/feed_snapshot.example.csv)

| 列 | 必須 | 内容 |
|---|---|---|
| `snapshot_id` | yes | refresh/requestごとのランダムID |
| `viewer_hash` | yes | salt付きhash。生のuser IDやhandleは禁止 |
| `requested_at` | yes | timezone付きISO-8601 |
| `position` | yes | 表示順。1始まり、snapshot内で一意 |
| `post_id` | yes | 公開post ID。snapshot内で一意 |
| `proxy_score` | yes | 同時点で計算したxalgo代理スコア |
| `in_network` | no | `true` / `false` / `unknown` |
| `media_type` | no | `text` / `image` / `video`等 |
| `view_bucket` | no | 事前定義した`low` / `mid` / `high`等 |
| `author_hash` | no | salt付きauthor hash |

`cookie`、`token`、`password`、`email`、`authorization`を名前に含む列は、誤ってcredentialを
保存しないよう読み込み時に拒否する。viewer hashのsaltもCSVやリポジトリへ保存しない。
同一snapshotではviewer hashとrequest時刻が一つでなければならず、最低3投稿を必要とする。

## 実行

```bash
python scripts/evaluate_feed_snapshot.py examples/feed_snapshot.example.csv
python scripts/evaluate_feed_snapshot.py my-anonymized-feed.csv --k 5,10,20 --json \
  > feed-evaluation.json
```

出力には入力ファイルのSHA-256、行数、snapshot数、生成時刻が入る。同じCSV、commit、`--k`
を保存すれば結果を再生成できる。

## 指標

- **Spearman**: 2順位の単調な一致。1が完全一致、-1が完全逆順。
- **Kendall tau-b**: 順序pairの一致率。代理スコアのtieを補正する。
- **NDCG@K**: 実feed上位ほど高いgraded relevanceを与え、代理score順の上位品質を測る。
  この実装は実順位`r`のrelevanceを`1/log2(r+1)`と定義する。
- **Top-K overlap**: 両方の上位K集合が何割一致するか。集合だけを見て順序は見ない。

複数snapshotはまずsnapshot単位で計算し、その後に単純平均する。全行を一つに混ぜないため、
閲覧者間・時刻間でproxy scoreの絶対scaleが異なっても順位評価を保てる。

`in_network`、`media_type`、`view_bucket`は各snapshot内で3件以上あるcellだけを再計算する。
小さいcellを無理に数値化せず、空の層は`{}`で返す。

## 解釈例

- 相関が高い: 表示された候補集合内で代理scoreと実順が関連した。
- 相関が低い: 重み、閲覧者履歴、非公開signal、後段補正のいずれかを代理scoreが欠く。
- NDCGが高く相関が低い: 上位候補は拾えているが、中下位の順序が違う可能性。
- Top-K overlapが高くNDCGが低い: 候補集合は近いが上位内の並べ方が違う可能性。

いずれも「代理scoreを上げれば露出が増える」という因果効果は示さない。実際のランカーが
先に表示位置を決め、その位置がengagement countへ影響する逆向きの経路があるためである。
