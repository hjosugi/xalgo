# [research] Phoenixデモのaction indexとoutput head順を確定する

## 背景

`phoenix/run_pipeline.py`はserver action enumの値（FAV=1、REPLY=4等）をmodel outputの
列indexとして使う。一方、`phoenix/runners.py::ACTIONS`では列0=favorite、1=reply、
4=clickとなっており一致しない。

## 完了条件

- [ ] artifact/checkpoint側の正しいhead順を上流へ確認する
- [ ] 6定数すべてについて期待headと実headの対応表を確定する
- [ ] xalgoの`repo_demo`を修正するか、互換性を保った新presetを追加する
- [ ] 監査scriptのfixtureと回帰testを追加する
- [ ] 本番不具合と断定せず、公開デモ契約の問題として報告する

## 再現

```bash
python scripts/audit_model_contract.py
```

## 2026-07-22追加調査

- 上流`main`は引き続きcommit `0bfc2795d3`で、6件のindex差も同じ。
- artifactのranker `model_params.npz`もRange取得して検査した。
- 出力は`unembeddings.npy (128, 19)`、履歴action入力は
  `action_projection.npy (19, 128)`だが、列ごとのaction名metadataはない。
- 両行列のcosine similarityにもsemantic順を確定できる安定した1対1対応はなかった。

このため公開物だけで正しいhead順を断定せず、上流確認を残す。
