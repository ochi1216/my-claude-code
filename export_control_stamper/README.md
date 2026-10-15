# 該非判定承認の自動化(export_control_stamper)

Power Automate から届く「[Approval request] 該非判定 〈品名〉」のメールを受けて、
該非判定証明書(Excel)に**承認者の印影を挿入**し、結果を Teams へ通知する。
**最終承認ボタンは、人(越智さん)が押す**。自動化するのは、手作業の次の部分である。

```
メール → リンクを開く → 添付の「…_該非判定証明書.xlsx」を開く → H15を選択
      → 挿入 → ピクチャ → セルの上に配置 → このデバイス → 印影を選ぶ
      → 位置を目視確認 → タブを閉じる(自動保存)          ← ここまでを自動化
      → メールに戻って「承認」→ コメント「Approved」→ 送信  ← 人が行う
```

## 状態

**実装済み・ローカル検証済み。実機(Windows / Power Automate)では未検証。**
コネクタの `operationId`・パラメータ名・戻り値の形は**未実測**で、実測するまで
フローの生成は止まる(推測値では作らない)。詳細は `docs/GATE_STATUS.md`。

## Power Automate の GUI は、ほぼ触らない

安否確認ツール(`power_automate_safety_checkin/`)で実機確認済みの方式を使う。
**フローの定義(JSON)をスクリプトで生成し、`pac solution import` で取り込む。**

| 作業 | このツールでの扱い |
| --- | --- |
| フローの組み立て(アクション・条件・式・カード) | **すべて生成**。GUIで組まない |
| 以降の修正・再展開 | コマンドだけ(生成 → pack → import) |
| operationId などの実測 | 使い捨てフローを**1本**作り、エクスポートして要約(アクションを置くだけ) |
| 接続のサインイン | GUI(認証情報を預ける操作のため、自動化しない) |
| フローを「オンにする」 | GUI(接続の紐付けが取り込み時に指定できない場合は、アクションごとの選び直しも) |

GUIに触る回数と手順は `docs/MEASUREMENT_GUIDE.md` に全部書いてある。

## 安全の設計

- **dryRun が既定。** `dryRun=true` の間は、添付ファイルを差し替えない。作業ライブラリの
  コピーにだけ押印し、結果を通知する。本番へは、設定を変えて生成し直す(`[本番モード]` と表示)
- **元のファイルを守る。** 押印は作業コピーに対して行い、複製の前に `_orig` を退避する
- **二重押印をしない。** 処理済みの記録、Office Script の図形検出の二重の防御
- **テンプレートが変わったら止まる。** シート名・15行目の承認者名が違えば中止する
- **失敗が見える。** 失敗したアクション名とメッセージを、Teams と記録リストへ残す
- **承認は人が押す。** 結果は、通知の「押印後のファイルを開く」で目視確認してから

## ファイル構成

```
export_control_stamper/
├── README.md / CHANGELOG.md / requirements.txt
├── deploy_config.example.json          # 設定のひな形(deploy_config.json はコミットしない)
├── office_scripts/
│   ├── stamp_approver_20261006_01.ts   # 印影の挿入(Excel Online の Office Script)
│   ├── inspect_shapes_20261006_01.ts   # 手作業の印影の位置・サイズを測る(読み取り専用)
│   └── test_stamp_20261006_01.mjs      # 上のロジックの模擬テスト(Node.js)
├── flows/
│   ├── build_flows_20261006_01.py      # フロー(JSON)とSolutionを生成
│   ├── verify_flows_20261006_01.py     # 生成物の構造検証(テナント不要)
│   └── summarize_export_20261006_01.py # 使い捨てフローのエクスポートを、実測用に要約
├── cards/                              # Teams に投稿する Adaptive Card
└── docs/
    ├── MEASUREMENT_GUIDE.md            # 実測の手順書(GUI操作の全て)
    ├── FLOW_SPEC.md                    # フローの設計と、その理由
    └── GATE_STATUS.md                  # 実機で未確認の項目と、完了条件
```

## 使い方(概要)

詳細は `docs/MEASUREMENT_GUIDE.md`。

1. SharePoint にライブラリ(`ECS_Work` / `ECS_Stamp`)を作り、印影を置く
2. Excel Online に Office Script を登録する
3. 使い捨てフローを1本作り、エクスポートして要約し、`deploy_config.json` の `measured` を埋める
4. 生成 → 検証 → 取り込み

```powershell
cd flows
python .\verify_flows_20261006_01.py                                       # 自己検証(設定不要)
python .\build_flows_20261006_01.py --config ..\deploy_config.json --out .\src
pac solution pack --zipfile .\ExportControlStamper.zip --folder .\src
pac solution import --path .\ExportControlStamper.zip
```

Office Script のテスト(Node.js 22.13 以降):

```powershell
cd office_scripts
node --no-warnings .\test_stamp_20261006_01.mjs
```

## 未確認・注意

- 輸出管理規程上、印影の自動貼付が許容されるかは**未確認**。本番(`dryRun=false`)への
  切替の前提条件
- 印影の画像は、**Git に入れない**。SharePoint の専用ライブラリ(越智さんのみアクセス可)に置く
- 取り込み時の接続参照の指定(`--settings-file`)は**未実測**
- 承認の代行ができない、という認識(Approvals コネクタ)は**未確認**
