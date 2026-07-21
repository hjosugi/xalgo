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
- 代表的な過去差分に対する自動テストがある
- 誤検知と見逃しの理由がドキュメント化される
- PR API有効・無効の両ケースをテストする
