# solution/

このフォルダは空の状態でコミットされている。

`scripts/deploy_solution_*.ps1（最新版） -Action export-unpack ...` を実行すると、
DEV環境で構築したPower AutomateのSolution一式(フロー定義・接続参照等)が
`solution/<SolutionName>/` としてunpackされ、ここに配置される。

## コミット前の確認事項

unpackされたファイルには、環境固有の識別子が含まれる場合がある。
`CLAUDE.md`および`docs/16_セキュリティ・個人情報`の方針に従い、コミット前に
以下を確認すること。

- Tenant ID、Team ID、Channel ID等のGUIDが平文で含まれていないか
  (接続参照は環境変数化されているのが望ましい)
- 実在の社員メールアドレスが含まれていないか

問題があれば、コミット前に該当箇所を環境変数・パラメータ化するか、
`.gitignore`で該当ファイルのみ除外すること。
