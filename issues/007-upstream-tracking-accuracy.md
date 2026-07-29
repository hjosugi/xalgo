# [analysis] 上流追跡の検知精度評価と回帰コーパス

## 現状
`scripts/track_upstream.py` はランキング関連パスのcommitを監視し、上流の
PR APIが利用可能ならmerged PRの変更ファイルも検査する。上流がPR APIを
404にしている間はcommit監視にフォールバックし、その状態をレポートする。

## 検証方法
1. 過去commitを「ranking / policy / unrelated」に人手分類して回帰コーパス化
2. 現在のパス判定でprecision / recallを測定
3. `grox/`（スパム分類・PTOS）を別カテゴリとして検知
4. Rust / PythonのAST差分で重み、式、アクション集合の変更を構造化
5. 同一commitとmerged PRの重複通知を抑止

## 完了条件

- [x] 公開3 commit由来の25ファイルをranking / policy / unrelatedへ人手分類する
- [x] path判定のprecision / recall / F1 / category accuracyを再生成できる
- [x] Grox spam・post safety・PTOSをpolicyとしてrankingと分離する
- [x] Python ASTとRust構造抽出で重み・式・action集合の差を構造化する
- [x] 同一merge commitのcommit/PR重複通知を抑止する
- [x] 代表的な過去差分に対する自動testがある
- [x] 誤検知と見逃しの理由がドキュメント化される
- [x] PR API有効・404の両ケースをtestする

## 実装

```bash
python scripts/track_upstream.py --evaluate-corpus
python scripts/track_upstream.py --evaluate-corpus --json
```

コーパスは`state/upstream_tracking_corpus.json`、評価方法と限界は
`docs/upstream-tracking-evaluation.md`を参照。公開履歴が3 commitしかないため、
25件はcommit数ではなく、そのcommit群に含まれる代表ファイル数です。
