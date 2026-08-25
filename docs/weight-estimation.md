# 匿名feed順位からの重み推定

`scripts/estimate_feed_weights.py`は、同一viewer・同一refresh内の表示順と`p_ACTION`特徴から
pairwise logistic ranking modelを学習する。上位投稿と下位投稿の特徴差へ正のscoreを与える
係数を推定し、2026年8月に公開されたHome Mixer defaultと同じfeature集合で比較できる。

これは**本番重みの復元ではない**。公開countから作ったrateは露出後の群集平均であり、
閲覧者別Phoenix予測ではない。出力は入力cohort内の順位との関連を示すだけで、production
feature switch、因果効果、未表示候補を識別しない。

## privacy-safe CSV

train/testとも次の列を使う。

| 列 | 内容 |
|---|---|
| `snapshot_id` | refresh/requestごとのランダムID |
| `viewer_hash` | 同じ非公開saltで作った`sha256:` + 64桁hex |
| `requested_at` | timezone付きISO-8601 |
| `position` | snapshot内の実表示順、1始まり |
| `post_id` | 公開post ID |
| `author_hash` | 同じ非公開saltで作った`sha256:` + 64桁hex |
| `p_ACTION` | `p_favorite`等の有限な`[0,1]`特徴。train/testで列集合を一致させる |

cookie、token、email、raw viewer/author IDやhandleを含む列は拒否する。saltはCSVやrepositoryへ
保存しない。author-disjoint検証のため、train/testのauthor hashは同じsaltで生成する。

## 実行

実cohortでは既定でtrain 50行、test 20行以上を要求する。

```bash
python scripts/estimate_feed_weights.py train.csv \
  --test-csv test.csv --json > weight-estimation.json
```

同梱CSVはschemaと再現方法を示すsynthetic fixtureであり、実測結果ではない。小さいため
minimum gateを明示的に下げる。

```bash
python scripts/estimate_feed_weights.py \
  examples/weight_estimation.train.example.csv \
  --test-csv examples/weight_estimation.test.example.csv \
  --min-train-rows 6 --min-test-rows 6 --json
```

## 出力と完了判定

- train/test SHA-256、tool SHA-256、optimizer設定
- 推定係数とL1正規化値
- 同じfeatureだけを抜き出した公開defaultとcosine similarity
- train/held-outのpairwise accuracy、logistic loss、Spearman、Kendall tau-b
- train/testのunique author数、author overlap 0、post overlap 0

`evaluation_mode=author_disjoint_held_out`かつ`overlapping_authors=0`が、コード上の
author-disjoint gateである。Issue #1/#11を実測完了にするには、synthetic fixtureではなく
実viewerから安全に匿名化したtrain/test CSVでこのgateを通したreceiptが必要になる。

## 限界

- 表示された候補しかなく、position/exposure/selection biasを除去しない。
- authorを分離してもviewer、topic、時刻の交絡は残る。
- 係数scaleはfeatureの定義と分布に依存し、公開defaultとの数値一致を期待できない。
- 実feed取得は自動化しない。X login、cookie、tokenを受け取らない。
