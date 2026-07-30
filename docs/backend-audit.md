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

## 2026-07-30 固定cohort監査（3/3・完了）

### Protocol

[`examples/backend_audit_cohort.txt`](../examples/backend_audit_cohort.txt)に120件を固定した。
109件は公式Phoenix artifact
`fbc6017d00588754e22e0c7eb2f786a008a74d309c03c8085fa2fad418a83dac`の
`sports_corpus.npz`から等間隔に選び、11件は`validate_popular.py`の既存標本である。

- cohort file SHA-256:
  `0ad1b7b44b76e853a4a67dfeb5a9be9496797422067f6ddc9dcb99c80a480f11`
- ordered status ID SHA-256:
  `f5029a47d466dbfb6c31f75bceee8e43243a9f254c29a15ee423e56a86323760`
- snapshot開始: 2026-07-30 07:27:32 UTC
- snapshot SHA-256:
  `610017931a9bbe0d993b0ca0d118cba799d4c5799ca34bbf159c0f0800e18ac5`
- 2回目snapshot開始: 2026-07-30 08:00:15 UTC
- 2回目snapshot SHA-256:
  `26258af8b2257da0b08a57064422bc460b2a9342ef11875f4a8440b9b5922a9b`
- 3回目snapshot開始: 2026-07-30 10:29:20 UTC
- 3回目snapshot SHA-256:
  `5843f102891f1e9d11ba4ab79c4339c8942885ef63e9ff1fe5aae8e3e8a10036`
- 最終集約 SHA-256:
  `2a82a1d614285f02e64ac5ffb32b10637f661f7006bb866236dcfe53a573e239`

receiptにはstatus ID、時刻、成功・失敗class、latency、公開count、動画有無だけを保存する。
本文、著者、URL、cookie、token、credentialは保存しない。

```bash
python scripts/audit_backends.py \
  --input-file examples/backend_audit_cohort.txt \
  --min-posts 100 \
  --delay 0.05 \
  --receipt state/backend-audits/snapshot-2026-07-30-01.json

python scripts/analyze_backend_snapshots.py \
  state/backend-audits/snapshot-2026-07-30-*.json
```

### Tombstoneを成功扱いした不具合

Syndicationは削除・非公開投稿にHTTP 200で`TweetTombstone`を返す。従来はこれを空の
`PostData`へ変換したため、初回のpreliminary runで成功率120/120と誤集計した。
`id_str`が要求IDと一致することを必須にし、tombstoneを`LookupError`へ変更した。
preliminary receiptは正式結果に使わず、修正版で同じ120件を再取得した。

### 3回集約結果

成功率区間はWilson 95%、latencyは成功requestのみで計算した。

| backend | 成功 | 成功率 | Wilson 95% | median | p95 | views coverage |
|---|---:|---:|---:|---:|---:|---:|
| FxTwitter | 321/360 | 89.2% | 85.5–92.0% | 355 ms | 458 ms | 89.2% |
| VxTwitter | 321/360 | 89.2% | 85.5–92.0% | 81 ms | 203 ms | 0% |
| Syndication | 318/360 | 88.3% | 84.6–91.3% | 339 ms | 659 ms | 0% |

全backendで取得不能だった13件を除くcohort profileはvideo 21件、non-video 86件。
投稿日は2025-12-30から2026-07-21まで6日に分散した。

共通取得できた投稿のcount差:

| pair / field | 比較 | 完全一致 | 平均相対差 | 最大相対差 |
|---|---:|---:|---:|---:|
| Fx / Vx likes | 321 | 283 | 0.0163% | 1.299% |
| Fx / Vx replies | 321 | 319 | 0.00132% | 0.211% |
| Fx / Vx retweets | 321 | 314 | 0.000479% | 0.0647% |
| Fx / Syndication likes | 318 | 305 | 0.0130% | 1.299% |
| Fx / Syndication replies | 318 | 318 | 0% | 0% |

### 最終判断

3回全ての標本内順序と最終集約順は、現行と同じ
`FxTwitter → VxTwitter → Syndication`だった。FxTwitterとVxTwitterは同じ成功率だが、
FxTwitterだけがviews/bookmarksを取得できるため第1候補を維持する。

監査時の12秒timeoutに対し、全1,080試行の最大レイテンシは1,587ms、5秒以上は0件、
timeout系失敗も0件だった。順序は変更せず、各backendのrequest timeoutを5秒へ短縮する。
これにより3 backend全失敗時の理論上限を36秒から15秒へ抑える。これは3時間帯の固定cohort
に基づく標本判断であり、公開endpointのSLAを意味しない。
