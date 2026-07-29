# 上流追跡の精度評価

## 回帰コーパス

`state/upstream_tracking_corpus.json`は、`xai-org/x-algorithm`の公開`main`にある
3 commit（`aaa167b3de8a`、`e414c171ed68`、`0bfc2795d308`）から代表25ファイルを
人手分類した固定コーパスです。

- `ranking`: Home Mixer、candidate pipeline、Phoenix、reply rankingなど順位へ直接関与。
- `policy`: Groxのspam、post safety、PTOS。順位式とは分けて通知する。
- `unrelated`: transport、telemetry、licenseなど。

```bash
python scripts/track_upstream.py --evaluate-corpus
python scripts/track_upstream.py --evaluate-corpus --json
```

このコーパスは母集団からの無作為標本ではありません。precision/recallは分類規則の
回帰指標であり、将来の上流変更に対する統計的な性能保証ではありません。

## 構造差分

trackerは対象ファイルのpatchから、次の追加・削除を構造化します。

- Python: 標準`ast`でassignment、function、action literal、関連する式を抽出。
- Rust: dependencyを増やさない構文抽出でconst/static、function、struct field、
  action token、関連する式を抽出。

完全なbefore/after sourceがある場合は
`diff_source_structure(path, before, after)`を直接利用できます。GitHub commit APIが
返すpatchは断片なので、parseできないPython断片は正規表現へfallbackします。
Rust側はtree-sitter/rustc ASTではなく、公開監視を軽量に保つための構造抽出です。

## commitとPRの重複

PR APIが利用可能な場合、merged PRの`merge_commit_sha`が同じ監視windowのcommitに
含まれていればPR側を重複として除外します。PR APIが404の場合は従来どおりcommit監視を
継続します。削除数は`deduplicated_pull_request_count`へ出力します。

## 既知の誤検知

- `README.md`はmodel contract driftを拾うため常時監視するので、文章だけの変更も通知し得る。
- candidate/query hydrator配下はmodel入力へ影響し得るため広く監視し、telemetry的変更も
  同じdirectoryなら通知し得る。
- patch内の`score`や`action`がコメント・test名だけでもsignal lineとして表示され得る。

## 既知の見逃し

- 新しいdirectoryへranking/policy処理が追加され、path規則も更新されなかった場合。
- GitHub APIが巨大diffのpatchを省略した場合、path通知はできても構造差分は空になる。
- renameだけでpatchがない場合、semantic changeは構造化できない。
- Rust抽出はmacro展開や型解決を行わないため、macro内だけの式変更を識別できない。

新しい上流構成を検知したときは、Issueを確認してからコーパスとpath規則を同時に更新します。
