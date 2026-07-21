# [research] Phoenix READMEと配布artifactのmodel config driftを追跡する

## 背景

2026-05-15 releaseのroot READMEは`256-dim / 2-layer`、Phoenix READMEは
`128-dim / 4-layer`と記載する。配布artifact内のretrieval/ranker configは後者と一致する。

## 完了条件

- [ ] Git LFS OIDとconfig抽出結果を検証artifactとして保存する
- [ ] root/Phoenix README変更時に自動監査する
- [ ] artifact pointer変更時にもIssueを起票する
- [ ] 既知driftと新規driftを区別して通知する
- [ ] 上流で修正されたcommit/PRをIssueへ記録する
