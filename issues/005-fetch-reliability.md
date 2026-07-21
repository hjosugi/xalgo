# [analysis] 取得バックエンドの信頼性

## 目的
fxtwitter / vxtwitter / syndication の欠損率・レート制限・数値ズレを測る。

## 検証方法
同一ポスト100件を3バックエンドで取得し、likes/replies の一致率、
views 欠損率、失敗率を記録。フォールバック順を最適化する。
