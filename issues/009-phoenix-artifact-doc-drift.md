# [research] Phoenix READMEと配布artifactのmodel config driftを追跡する

## 背景

2026-05-15 releaseのroot READMEは`256-dim / 2-layer`、Phoenix READMEは
`128-dim / 4-layer`と記載する。配布artifact内のretrieval/ranker configは後者と一致する。

## 完了条件

- [x] Git LFS OIDとconfig抽出結果を検証artifactとして保存する
- [x] root/Phoenix README変更時に自動監査する
- [x] artifact pointer変更時にもIssueを起票する
- [x] 既知driftと新規driftを区別して通知する
- [ ] 上流で修正されたcommit/PRをIssueへ記録する

## 2026-07-30 追加drift

full artifactを使った実推論で、Phoenix READMEが`~537K sports posts`と説明する
`sports_corpus.npz`は、配布実体では84,564件（representation shape
`(84564, 128)`）だった。config driftと同じ固定commit
`0bfc2795d308f90032544322747caacd535f75ae`で再現した。

常時監査へこの件数検査を加えるには外側ZIPで圧縮された約41MBのcorpus member取得が
必要になるため、約68KBという現行監査の性質は変えず、full inference receipt側で固定する。
詳細: [`docs/phoenix-local-inference.md`](../docs/phoenix-local-inference.md)
