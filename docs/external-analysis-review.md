# 外部分析・GitHub実装・研究論文レビュー

## 読み方

このレビューは、情報源を次の優先順位で扱う。

1. 配布artifactの設定・実行結果
2. pinned commitの公式コード
3. 公式README・公式論文
4. 第三者実装
5. 解説記事

下位の情報源が上位と衝突した場合は上位を採用する。「記事に複数回書かれている」は独立した
証拠にならず、同じ2023年表や同じ推測を転載している場合がある。

## 公式ソース

| ソース | 得られるもの | 限界 |
|---|---|---|
| [`xai-org/x-algorithm`](https://github.com/xai-org/x-algorithm/tree/0bfc2795d308f90032544322747caacd535f75ae) | 2026 pipeline、Phoenix推論、mini checkpoint | production設定・学習系・一部内部依存なし |
| [`phoenix/README`](https://github.com/xai-org/x-algorithm/blob/0bfc2795d308f90032544322747caacd535f75ae/phoenix/README.md) | Two-Tower、candidate isolation、mini config | root READMEとmodel sizeが矛盾 |
| [`xai-org/grok-1`](https://github.com/xai-org/grok-1) | 元Transformerの系譜、Grok-1仕様 | Phoenixの学習法ではない |
| [`twitter/the-algorithm`](https://github.com/twitter/the-algorithm) | 2023 serving architecture | 2026 Phoenixの現行値ではない |
| [`twitter/the-algorithm-ml`](https://github.com/twitter/the-algorithm-ml/blob/b85210863f7a94efded0ef5c5ccf4ff42767876c/projects/home/recap/README.md) | 旧MaskNet、2023-04-05の重み | 現行Phoenixへ転用不可 |

## 第三者GitHubリポジトリ

### VeritasActa/x-algorithm-receipts

[`x-algorithm-receipts`](https://github.com/VeritasActa/x-algorithm-receipts)は、公式Phoenix
デモを実行し、code commit、artifact/config、input/outputのhashを束ねて署名する。
再現性と監査証跡の設計として有用である。

ただしreceiptが証明するのは「この入力とこの公開checkpointでこの出力が出た」ことであり、
本番Xが同じcheckpointを使ったこと、公平性、推薦品質、実際の表示順位までは証明しない。

### lxyang20131208-star/x-algorithm-skills

[`x-algorithm-skills`](https://github.com/lxyang20131208-star/x-algorithm-skills)は、公開コードを
creator向け助言へ翻訳している。閲覧者別予測、負signal、現行重み非公開という注意は妥当。
一方、次の主張は証拠を分ける必要がある。

- 「entity密度を上げるとvectorが鋭くなる」: 公開Phoenix rankerに本文token入力はない。
- 「author embeddingは誰が反応したかで学習」: もっともらしいが学習コード・データがない。
- 「OON penaltyは1未満」: 補正コードはあるが実値は非公開。状況により別係数も使う。
- 「19 action」: Python出力、continuous出力、Home Mixer 22信号が一致しない。

調査時点でGitHub上の多くは公式repoの未変更forkであり、独自検証として特に参考になったのは
上記二つだった。star数は品質の根拠にせず、実装内容だけを評価した。

## 解説記事で頻出する主張の検証

確認対象には
[`VibeCom`](https://www.vibecom.app/blog/x-released-phoenix-its-new-recommendation-algorithm-heres-what-actually-changed-)、
[`TechTimes`](https://www.techtimes.com/articles/316791/20260518/xais-may-15-update-makes-xs-phoenix-ranking-engine-fully-runnable-one-reply-outweighs-150-likes.htm)、
[`needhelp.icu`](https://needhelp.icu/blogs/xai-x-algorithm-phoenix/)、
[`Cryptul`](https://cryptul.co.jp/insights/articles/154-x-algorithm-analysis)、
[`singhajit`](https://singhajit.com/system-design/x-twitter-for-you-algorithm/)、
[`Medium`](https://medium.com/@roanmonteiro/reading-the-x-algorithm-a-production-recsys-tour-through-xai-org-x-algorithm-1dea10eb33b7)
等を含めた。

| よくある主張 | 判定 | 理由 |
|---|---|---|
| 「1 reply = 27 likes」「author reply = 150 likes」 | 2023限定 | 旧重み13.5/0.5、75/0.5の比。2026値ではない |
| 「2026の実weightが公開された」 | 誤り | `xai_feature_switches`から注入され数値なし |
| 「PhoenixはGrokが本文を読む」 | 少なくとも公開rankerでは誤り | `RecsysBatch`に本文tokenがない |
| 「フォロワー数を直接特徴にする」 | 公開Phoenixでは未確認 | user/post/author IDと履歴が中心。間接相関はありうる |
| 「コードは完全なproduction system」 | 過大 | 公式はrepresentativeと説明し、内部依存も欠ける |
| 「公開checkpointで実際のFor You順位を再現」 | 誤り | sports corpus、mini model、非公開weight/filter/context |
| 「重みが大きいactionほど常に重要」 | 誤り | 寄与は`weight × probability`。発生率とcalibrationが必要 |
| 「content tipsを投稿前に正確にscoreできる」 | 未立証 | 新規投稿IDの学習済み表現と閲覧者contextを取得できない |

特に2023値を2026記事の見出しに使うケースが多い。歴史比較には有用だが、現行攻略法として
扱うべきではない。

## 推薦研究との比較

- Googleの
  [Deep Neural Networks for YouTube Recommendations](https://research.google/pubs/deep-neural-networks-for-youtube-recommendations/)
  はcandidate generationとrankingを分ける大規模推薦の代表例。Phoenixの二段構成を理解する
  ための最も近い概念資料だが、X固有の実装証拠ではない。
- [SASRec論文](https://arxiv.org/abs/1808.09781)と
  [公式実装](https://github.com/kang205/SASRec)はself-attentionで行動列から次itemを推薦する。
  PhoenixのUser Towerを理解しやすい。
- [BERT4Rec論文](https://arxiv.org/abs/1904.06690)と
  [著者実装](https://github.com/FeiSun/BERT4Rec)はbidirectional Transformerとmasked item
  predictionを使う。Transformer推薦でもmaskとlossで意味が大きく変わる例である。
- Pinterestの[TransAct](https://arxiv.org/abs/2306.00248)は、リアルタイム行動sequenceを
  feed rankingに使うproduction事例。履歴をrequest時contextとして扱う発想が近い。
- Googleの[Multi-gate Mixture-of-Experts](https://research.google/pubs/modeling-task-relationships-in-multi-task-learning-with-multi-gate-mixture-of-experts/)
  は複数action予測でtask共有を制御する代表研究。ただしPhoenixがMMoEを使う証拠ではない。

## 分析に採用する原則

- URLスコアには必ず「代理指標」と表示し、Phoenix scoreと呼ばない。
- 2023重み、2026デモ値、2026本番未知値を混ぜない。
- code、artifact、推論、第三者主張を別列に記録する。
- 相関には標本数、期間、選び方、信頼区間を付ける。
- popularity上位だけで検証せず、低・中・高viewを層化抽出する。
- feed順位の因果検証ではposition/exposure/selection biasを扱う。
