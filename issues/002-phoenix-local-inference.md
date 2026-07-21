# [analysis] Phoenix mini モデルのローカル推論

## 目的
上流の Git LFS 配布 mini Phoenix (256-dim / 4 heads / 2 layers, 約3GB) を
phoenix/run_pipeline.py で動かし、実際の P(action) 分布を観測する。

## 手順
1. git lfs pull で artifacts 取得
2. uv sync して retrieval → ranking を実行
3. 各アクション確率のヒストグラムを取り、経験的レート (likes/views) と比較

## 論点
- 経験的レートは Phoenix 予測の proxy としてどの程度妥当か
- スポーツコーパス以外への一般化
