# [analysis] Phoenix mini モデルのローカル推論

## 目的
上流の Git LFS 配布 mini Phoenix (artifact実体は128-dim / 4 heads /
4 layers、約3GB) をphoenix/run_pipeline.pyで動かし、実際のP(action)分布を観測する。

## 完了条件

- [x] LFS SHA-256とZIP CRCを検証してartifactを取得する
- [x] `uv sync --frozen`後、upstream testとretrieval → rankingを実行する
- [x] 200候補 × 19列の確率exportを2回生成し、決定性を確認する
- [x] 全列の分位点とヒストグラムを保存する
- [x] 公開count proxyと記述的に比較し、比較不能な範囲を明記する

## 論点
- 経験的レートは Phoenix 予測の proxy としてどの程度妥当か
- スポーツコーパス以外への一般化

## 2026-07-30 結果

- upstream `0bfc2795d308f90032544322747caacd535f75ae`を固定した。
- 2,903,518,802 byteのartifactはLFS SHA-256
  `fbc6017d00588754e22e0c7eb2f786a008a74d309c03c8085fa2fad418a83dac`と一致した。
- upstream unit test 34件、公式pipeline（84,564件 → retrieval 200件 →
  ranking 200件）を完走した。標準実行は15.8秒だった。
- 3,800確率のexportを2回生成し、同一SHA-256
  `7214149cc04f68a451849b00f49fef78debb5b7471adb3d4bf463754d6d84e47`を得た。
- 公開count率はviewer別事前予測ではなく、candidate・時点も一致しないため、
  Phoenix probabilityのcalibration proxyとしては不十分である。
- sports以外への一般化は配布artifactだけでは評価不能であり、別corpus/checkpointまたは
  production観測が必要である。

再現手順、全19列のhistogram、proxy比較:
[`docs/phoenix-local-inference.md`](../docs/phoenix-local-inference.md)
