# 取得バックエンド監査

## 2026-07-21 スモークテスト

`scripts/validate_popular.py` の11投稿に対し、FxTwitter、VxTwitter、X embed
syndicationを個別に呼び出した。取得時刻は2026-07-21 12:52 UTC。

| backend | 成功 | 平均レイテンシ | likes | retweets | replies | views |
|---|---:|---:|---:|---:|---:|---:|
| FxTwitter | 11/11 | 366 ms | 11/11 | 11/11 | 11/11 | 11/11 |
| VxTwitter | 11/11 | 603 ms | 11/11 | 11/11 | 11/11 | 0/11 |
| syndication | 11/11 | 408 ms | 10/11 | 0/11 | 10/11 | 0/11 |

FxTwitterとVxTwitterの共通カウントを比較した結果:

| field | 比較数 | 完全一致 | 平均相対差 | 最大相対差 |
|---|---:|---:|---:|---:|
| likes | 11 | 5 | 0.0089% | 0.0374% |
| replies | 11 | 11 | 0.0000% | 0.0000% |
| retweets | 11 | 10 | 0.0057% | 0.0628% |

likesの小さな差は取得タイミング中にも値が増えることと整合する。単回・小標本なので、
サービス全体のSLAや長期的な精度を表すものではない。

## 発見・修正した不具合

旧VxTwitter URLは `/Twitter/status/{id}` という固定ユーザー名を含み、同じ投稿に
対して古いカウント（例: likes 9対35,784）を返した。ユーザー名を省略した
`/status/{id}` ではFxTwitterとほぼ一致したため、`xalgo/fetch.py` を修正し、
URLに固定ユーザー名を戻さない回帰テストを追加した。

## 暫定判断

標本内ではviewsとbookmarksを取得できるFxTwitterを第1候補に維持する。
第2候補はviewsを取得できないもののretweetsを保持するVxTwitter、第3候補は
likes/repliesだけを取得するsyndicationとする。100件以上・複数時間帯の測定は
Issue #5で継続する。
