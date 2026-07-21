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
