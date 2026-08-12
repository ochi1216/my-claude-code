# 引継ぎ: word_translation の Gemini APIプロキシ対応（TYPE C）

2026-08-12 作成。`outlook_total_organizer`（TYPE A）・`excel_translation`・`pdf_translator`・
`ppt_translation`（TYPE C、**いずれも実機で動作確認済み・mainへマージ済み**）を同じ方式へ
移行した実作業から得た知見をまとめたもの。
**「先に読むと事故を防げること」を優先して書いてある。**

対象（移行元）: `C:\Users\nx023836\Documents\PythonScripts\word\word_translator\word_translation_20260306_01.py`
新ファイル名: `word_translation_YYYYMMDD_01.py`（**作業当日の日付にすること**。`date` コマンド等で確認する）

**この資料の使い方**: 新しいClaude Codeセッションを開き、この資料と `word_translation_20260306_01.py`
をアップロードして作業を依頼する。この資料は `my-claude-code` リポジトリのルートにも置いてあるため、
セッションからはリポジトリを読むだけでも参照できる。

---

## 0. 【最重要】この資料を書いた時点で、対象ファイルは読めていない

本資料は `word_translation_20260306_01.py` の**現物を持たない状態で**書いている。
先行5ツールの実作業から得た手順・ハマりどころ・シムの実物は確実な情報だが、
**word_translation 固有の内容（§5 の移行対象、§6 の付随ファイルの有無）は推測を含む。**

先行ツールでは、事前の設計提案書が「`from google.genai import types` が L21 にある」と書いていたが、
実物は旧SDK `google.generativeai` でそんな行は存在しなかった、という事故が起きている（§9-(5)）。
**着手時は必ず現物を読み、grep で実数を数えてから作業すること。本資料の記述と食い違ったら、
現物が正しい。**

そのうえで、先行ツールから確実に言えることは次のとおり。

| # | 箇所 | 何が起きるか |
|---|---|---|
| 1 | `genai.list_models()` による自動モデル検出 | **起動時にネットワークを叩くため、遮断下では初期化に失敗して `sys.exit(1)`。ツールが立ち上がらない**（`pdf_translator` / `ppt_translation` の両方で実際にこうなっていた） |
| 2 | `response.parts` の参照 | シムが `.parts` を持たないと `AttributeError` → 全バッチが3回リトライ後に失敗 |
| 3 | `safety_settings` | payloadへ載せないと `BLOCK_NONE` 指定が消え、内容によっては応答が空になる |
| 4 | `request_options={"timeout": N}` | 共通モジュールに同等機能なし。削除して挙動差を記録する |
| 5 | 付随ファイル | あるか無いかで作業量が変わる。**着手前にユーザーへ確認**（§6・§11） |

### 系譜について（知っておくと理解が早い）

`ppt_translation` の進捗表示クラスは、**PowerPointのツールなのに `WordProgressWindow` という
名前のまま**である（`ppt_translation_20260309_03.py` / `_20260812_01.py` の両方で確認済み）。
また日付を並べると次のようになる。

```
word_translation_20260306_01.py   ← 2026-03-06
ppt_translation_20260309_03.py    ← 2026-03-09（3日後）
pdf_translator_20260722_08.py     ← 2026-07-22（docstringに「ppt_translation の設計を踏襲」と明記）
```

つまり **word_translation がこの系統の祖先で、PPT → PDF と派生していった**可能性が高い。
`ppt_translation` と `pdf_translator` は Gemini 呼び出し部分がAST比較で**完全一致**していたので、
**word_translation も同じコードである可能性が高い**（＝移行差分をほぼそのまま当てられる）。

**ただしこれは推測。** 祖先である以上、逆に「後から入った改善が入っていない」可能性もある
（例: リトライ機構・フェイルファスト・ロギングが無い、進捗コールバックが無い等）。
着手時に必ず現物で確かめること。**無い機能を移行のついでに足さないこと**（スコープ外）。

---

## 1. 背景

会社PCからGemini APIへの直接アクセスが遮断された（2026-08-10頃）。対策として、共通モジュール
`gemini_client.py` の `generate_advanced()` を経由し、直接呼び出しが失敗したら自宅PCの
プロキシへ自動フォールバックする仕組みへ移行している。

移行済みのツール:

- `rtocs_organizer`
- `analog_ic_se_strategy_organizer`
- `outlook_total_organizer` … 2026-08-12 完了（TYPE A）
- `excel_translation` … 2026-08-12 完了。**実機で動作確認済み・mainへマージ済み（PR #6）**
- `pdf_translator` … 2026-08-12 完了。**実機で動作確認済み・mainへマージ済み（PR #7）**
- `ppt_translation` … 2026-08-12 完了。**実機で動作確認済み・mainへマージ済み（PR #8）**

今回の対象: **word_translation**（TYPE C = Git未管理）。これで**6ツール目**になる。

---

## 2. 参照資料（推測で書かず、必ず実物を読むこと）

- **最優先**: `my-claude-code` の `ppt_translator/ppt_translation_20260812_01.py`
  … 移行後の完成形。**シムは L69〜L263。ここから丸ごとコピーしてよい。**
  Wordツールとは「run単位で書式を保持する」という設計思想が同じなので、5ツールの中で
  **いちばん近い前例**。
- `my-claude-code` の `ppt_translator/ppt_translation_20260309_03.py` … 移行前。差分の取り方の参考。
- `my-claude-code` の `ppt_translator/tests/test_ppt_translation_20260812_01.py`
  … 95項目のテスト。**新規に書き起こさずコピーして差分を当てるのが速い**（§8）。
- `my-claude-code` の `ppt_translator/CHANGELOG.md` の `[20260812_01]` … 記載フォーマットの見本。
- `my-claude-code` の `ppt_translator/run_ppt_translator.bat` … 起動用batのひな形。
- 全体設計: `gemini-common-tools` リポジトリの `GEMINI_MIGRATION_HANDOVER.md`
- 共通モジュール本体: 同リポジトリの `gemini_client.py`。公開リポジトリなので匿名cloneで取得できる:
  `git clone --depth 1 https://github.com/ochi1216/gemini-common-tools`
  **payloadの送られ方（`_call_direct_advanced` / `_call_proxy_advanced`）を必ず自分の目で確認すること。**
  「プロキシは payload をそのまま透過し、`model` だけ `_gemini_model` フィールドに載せ替える」という
  事実を知らないと、`safetySettings` を載せてよいか判断できない。
- 前回の引継ぎ資料: `HANDOVER_ppt_translation_gemini_proxy.md`（本資料はこれの改訂版）

---

## 3. 移行の全体方針: 「互換シム」1つで置き換える

`genai` SDK の呼び出しを個別に全部書き換えてはいけない。`genai.Client` と同じインターフェースだけを
持つ薄い互換シムを1つ作り、**クライアント生成箇所だけ**を差し替える。

これにより、レスポンスを読む側（`response.text` を正規表現で解析して番号付きリストへ戻す処理）や、
リトライ・フェイルファスト・進捗表示のロジックは**一切変更しないで済む**。

**6ツールすべてでシムの形を揃えること。** 呼び出しの形は
`client.models.generate_content(model=..., contents=..., config=...)` に統一する。

---

## 4. Git環境の作り方（TYPE C 固有。ここを最初にやる）

リポジトリ: `ochi1216/my-claude-code`（セッション開始時にクローン済みのはず）

```bash
# 1. 指定された作業ブランチを作る（ブランチ名はセッション開始時に指示される）
git fetch origin main
git checkout -B claude/<指示されたブランチ名> origin/main

# 2. フォルダを作り、アップロードされた「現状のファイル」をそのまま置く
mkdir -p word_translator/tests
#   word_translation_20260306_01.py と、既にある付随ファイルをすべてコピー

# 3. ★重要★ ここで一度コミットする（＝移行前の基準点を作る）
git add word_translator && git commit -m "Add word_translation as-is (baseline before Gemini proxy migration)"
```

**手順3を必ず先に単独でコミットすること。** これをやっておくと、次のコミットの `diff` が
「移行で変えた箇所」だけになり、CHANGELOGに書く「変更関数」「未変更であることの証明」を
客観的に示せる。`ppt_translation` ではこれで「PPT処理側の13定義が旧版と完全一致」を証明できた。

そのうえで:

- 新ファイルは **`word_translation_YYYYMMDD_01.py`**（**作業当日の日付**。`v` 記号は付けない。
  同日再リリースは `_02`）。
- **旧版 `word_translation_20260306_01.py` は削除しない。** 併存させる（リポジトリの運用ルール）。
- フォルダ名は **`word_translator`**（＝実機の置き場所に合わせる）。
  ファイル名の接頭辞は **`word_translation`** のまま。
  **フォルダ名と接頭辞が違う点に注意**（`ppt_translator` / `ppt_translation` と同じ罠。
  起動用batのワイルドカードを書くときに間違えやすい）。
- ルートの `README.md` にツール一覧の項目を1つ追記する（既存の書式に合わせる）。
  **ここは他ツールのPRとぶつかりやすい。** `ppt_translation` のときは、作業中に
  `pdf_translator` のPRがmainへ入って README.md がコンフリクトした。両方残す形で解決すればよい。
- 最後に `git push -u origin <ブランチ名>`。PR作成とマージは**ユーザーから明示的に依頼されてから**行う。

---

## 5. 着手時に現物で確認すること（word_translation の移行対象マップ）

**行番号は書かない。現物が手元に無いため。** 代わりに、確認すべき箇所と「見つけ方」を書く。
`ppt_translation` で実際に変更が必要だったのは **`check_dependencies` / `init_gemini` /
`translate_batch_gemini` の3関数だけ**だった（`pdf_translator` でも同じ3つ）。
おそらく word_translation でも同じになる。

まず次を実行して実数を数える。

```bash
grep -n "genai\|GEMINI_API_KEY\|list_models\|safety_settings\|request_options\|response.parts\|generate_content\|import docx\|from docx" word_translation_20260306_01.py
```

| 確認箇所 | 対応 |
|---|---|
| `import google.generativeai as genai` | 削除 |
| `HAS_GEMINI` | 共通モジュールを読めたかどうかへ意味を変更 |
| `check_dependencies()` の `google-generativeai` | 共通モジュールのチェックへ差し替え（`python-docx` のチェックはそのまま残す） |
| `gemini_model = None`（グローバル） | シムのクライアントを入れる（名前は `gemini_client`。他5ツールと揃える） |
| `GEMINI_API_KEY` 必須ガード | `gemini_credentials_available()` へ（§9-(1)） |
| `genai.configure(api_key=api_key)` | 削除 |
| **`genai.list_models()` による自動モデル検出** | **削除。固定モデル名へ（最重要・§5-1）** |
| `if not gemini_model` | `if not gemini_client` へ |
| `safety_settings`（BLOCK_NONE ×4） | **payload の `safetySettings` へ載せる（§5-3）** |
| `gemini_model.generate_content(...)` | シム経由へ置換（§5-5） |
| `genai.types.GenerationConfig(temperature=...)` | ローカルの config クラス（`_GeminiGenerateConfig`）へ |
| `request_options={"timeout": N}` | **削除（同等機能なし・§5-4）** |
| **`if not response.parts:`** | **シムに `.parts` を持たせる（§5-2）** |
| `response.text.strip()` | 変更不要（シム対応済み） |

`import os` / `import sys` が既にあるかも確認する（シムが使う。無ければ追加）。

**Grounding（`google_search` / `tools=`）・`response_schema`・`system_instruction` は、先行5ツールでは
すべて未使用だった。** word_translation でも使っていない見込みだが、grep で確かめること。
使っていた場合もシムは対応済み（`_GeminiGenerateConfig` に口がある）。

**Word処理側（段落・run の走査、表・ヘッダー/フッターの処理、進捗ウィンドウ、ファイル選択）は
一切触らないこと。**

### 5-1. 【最重要】`genai.list_models()` で起動できなくなる

先行2ツール（`pdf_translator` / `ppt_translation`）はどちらも `init_gemini()` の中で
`genai.list_models()` を呼んで使用可能モデルを自動検出していた。これはネットワークアクセスを
伴うため、**遮断下では必ず例外 → 「API初期化エラー」ダイアログ → `sys.exit(1)`** となり、
**移行しない限り起動すらできない**状態だった。実機でもそのとおりだった。

共通モジュールに `list_models` 相当は無く、プロキシにも該当エンドポイントは無い。
**自動モデル検出は諦めて固定モデル名にする**のが正解。

```python
# 共通モジュール側の既定値と揃えつつ、環境変数で上書きできるようにする
GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def init_gemini(root_window):
    """Gemini呼び出しの事前チェック。
    移行前はここで genai.list_models() による自動モデル検出を行っていたが、
    ネットワークアクセスを伴うため遮断下では必ず失敗し、ツールが起動できなくなる。
    モデルは固定名（環境変数 GEMINI_MODEL で上書き可）を使う方式へ変更した。"""
    global gemini_client
    if _generate_advanced is None:
        messagebox.showerror("エラー", _gemini_common_module_error_message(), parent=root_window)
        return False
    if not gemini_credentials_available():
        messagebox.showerror("エラー",
                             "Gemini認証情報が設定されていません。\n"
                             "以下のいずれかを設定してください:\n"
                             "- 環境変数 GEMINI_API_KEY （直接接続用）\n"
                             "- 環境変数 GEMINI_PROXY_URL （自宅PCプロキシ経由用）\n\n"
                             "※ setx で設定した場合は、コマンドプロンプトを\n"
                             "　 開き直してから起動してください。", parent=root_window)
        return False
    gemini_client = _CommonGeminiClient()
    print(f"使用モデル: {GEMINI_MODEL_NAME}")
    return True
```

**副作用の申し送り**: 自動検出を外すため、指定モデルが使えない環境では 404 が出るようになる。
ただし `gemini-2.5-flash` は他5ツールで実績があり、実害はまず無い。CHANGELOGに明記すること。

### 5-2. 【要注意】`response.parts` を見ているはず

```python
if not response.parts:
    if logger: logger.warning(...)
    raise ValueError("Empty response from API")
```

シムに `.parts` を持たせて解決する。空応答のとき `[]` を返せば、**元の
「空ならValueErrorでリトライ」という挙動がそのまま保たれる**（ここが大事）。
`ppt_translation_20260812_01.py` の `_CommonGeminiResponse` は既にこの対応が入っている。

### 5-3. `safety_settings` を payload へ載せる

`safety_settings` は既にREST形式の dict のリスト（`category` / `threshold`）のはずなので、
**そのまま `payload["safetySettings"]` に入れればよい**。載せ忘れると `BLOCK_NONE` 指定が消え、
資料の内容によっては応答が空になり「一部バッチだけ翻訳されない」という切り分けにくい症状になる。

### 5-4. `request_options={"timeout": N}` は等価な置き換えができない

共通モジュールのタイムアウトは `gemini_client.py` 側の固定値（**直接15秒 / プロキシ60秒**）で、
呼び出し側から指定する口が無い。**引数は削除し、CHANGELOGに挙動差として明記する。**

実害は小さい。理由: このツールも3回リトライを自前で持っている見込みで、
`gemini_client` 側も「直接失敗 → 即プロキシへフォールバック」するため。
ただし**初回のバッチだけは直接呼び出しの15秒タイムアウトを待つぶん遅くなる**。
一度失敗すると `.gemini_direct_disabled_until` に記録され、以降は直接呼び出しをスキップして
プロキシ直行になる。**これは仕様どおりの挙動で、バグではない。**
実機で「最初だけ遅い」と報告されても慌てないこと。

### 5-5. 呼び出し側の置換後

```python
            # request_options={"timeout": N} は共通モジュールに同等機能が無いため削除。
            # タイムアウトは gemini_client.py 側の固定値(直接15秒 / プロキシ60秒)になる。
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL_NAME,
                contents=prompt,
                config=_GeminiGenerateConfig(temperature=0.1, safety_settings=safety_settings),
            )
```

---

## 6. 付随ファイル（今回は「ある」可能性が高い）

`ppt_translation` は `PythonScripts\excel\` 直下に単独で置かれており付随ファイルが1つも無かったが、
**今回は既に `PythonScripts\word\word_translator\` という専用フォルダがある。**
フォルダを切ってあるということは、**起動用bat・`requirements.txt`・`README.md` が既に置かれている
可能性が十分ある。**

**着手前に必ずユーザーへ確認し、あるなら実物をアップロードしてもらうこと**（§9-(2) の手戻りを防ぐ）。
無い場合は次の4つを新規に作る。

### (1) `requirements.txt`

```
# word_translation の依存ライブラリ
#
# Gemini API の呼び出しは共通モジュール gemini-common-tools の gemini_client.py
# 経由へ移行したため、旧SDK google-generativeai は 本バージョン以降不要。
# gemini_client.py 自体は requests を使うため、別途インストールが必要。

python-docx
requests      # gemini_client.py が使用
```

`requests` の追加は**必須**。起動用batが専用のvenvを作ってそこに
`pip install -r requirements.txt` する構成の場合、**`requests` を書いておかないと venv 内に
入らず、`gemini_client` の import が失敗する**（＝ツールは起動するがAI呼び出し時にエラー）。

**既に `requirements.txt` がある場合は、`google-generativeai` を削除して `requests` を足すだけ。**

### (2) `run_word_translator.bat`

`ppt_translator/run_ppt_translator.bat` をひな形にする。**そのままコピーせず、次の2点を必ず直すこと。**

- ワイルドカードを `word_translation_????????_??.py` にする
  （**フォルダ名は `word_translator` だがファイル名の接頭辞は `word_translation`**。ここを間違えると
  「起動対象が見つからない」で止まる）
- 表示文字列を「Word」に直す

認証情報のチェックは、**`GEMINI_API_KEY` と `GEMINI_PROXY_URL` の両方が空のときだけ**警告する形にする:

```bat
if not "%GEMINI_API_KEY%"=="" goto :run_tool
if not "%GEMINI_PROXY_URL%"=="" goto :run_tool
goto :warn_no_credentials
```

**このファイルは絶対にASCIIのみで書くこと。** 日本語を入れるとShift-JIS誤読で
`goto` が壊れて起動しなくなる（`pdf_translator/CHANGELOG.md` の `[20260722_02]` に実際の被害が
記録されている）。`chcp 65001` では直らない。書き終えたら必ず
`python3 -c "print(sum(1 for b in open('run_word_translator.bat','rb').read() if b>127))"`
で 0 になることを確認する。**既存のbatがある場合も同じチェックをかけること。**

### (3) `README.md`

`ppt_translator/README.md` の構成をひな形にする。特に次は必ず書く:

- 必要な環境変数は `GEMINI_API_KEY` / `GEMINI_PROXY_URL` の**どちらか一方以上**であること
- `gemini_client.py` の置き場所（上位の `common` を自動探索。`GEMINI_COMMON_DIR` で明示指定可）
- モデルが固定になったこと、`GEMINI_MODEL` で上書きできること
- 「最初のバッチだけ遅い」のは仕様であること

### (4) `CHANGELOG.md`

`ppt_translator/CHANGELOG.md` の書式（`## [YYYYMMDD_NN] - YYYY-MM-DD` + 追加ファイル/更新ファイル）に
合わせる。新規作成になる場合は、`[20260306_01]` までの履歴を元ファイルの docstring から起こして
1エントリにまとめておくと親切（先行ツールでは冒頭に変更内容が箇条書きで残っていた）。

---

## 7. シム実装

**`ppt_translator/ppt_translation_20260812_01.py` の L69〜L263 をそのままコピーする。**
`word_translation` に必要な要素（`.parts` / `safetySettings` / 上位ディレクトリ探索）は
すべて入っており、変更は不要。

コピーする範囲に含まれるもの:

- `_COMMON_DIR_CANDIDATES` の組み立て（上位1〜3階層の `common` を順に探索）
- `_gemini_common_module_error_message()`
- `_schema_to_jsonable()`
- `_GeminiGenerateConfig`（`temperature` / `safety_settings` / `system_instruction` ほか）
- `_CommonUsageMetadata` / `_CommonGeminiResponse`（**`.parts` 対応済み**）
- `_CommonGeminiModels`（**`safetySettings` を payload へ載せる処理を含む**）
- `_CommonGeminiClient`
- `gemini_credentials_available()`

コピー後にコメント文中の「PowerPoint」「ppt_translator」を「Word」「word_translator」へ直すこと
（動作には影響しないが、読む人が混乱する）。

### 探索パスについて（重要）

```
PythonScripts\
├── common\
│   └── gemini_client.py
└── word\
    └── word_translator\
        └── word_translation_YYYYMMDD_NN.py    ← ここから見て common は「2つ上」
```

**1つ上（`word\common`）では見つからない。** 上位を順に探す方式（1つ上・2つ上・3つ上）に
なっているので、コピーしたままで正しく解決する。`ppt_translation` と全く同じ階層構造。

### 改行コードに注意

先行ツールの元ファイルは **CRLF** だった。`ppt_translation` の移行では、置換を素朴に行うと
`\r` の扱いでマッチしない・改行が混在するという事故になりかけた。
**元ファイルの改行コードを `file` コマンド等で確認し、それを維持して書き出すこと。**
（Pythonで処理するなら `open(..., newline="")` で読み、`newline="\r\n"` で書く。）

また、元ファイルには**行末に空白だけが残っている行**があった。置換のマッチに失敗する原因に
なるので、行末空白を許容する形で照合するか、現物をよく見て文字列を作ること。
**行末空白を一括除去してはいけない**（未変更のはずの関数までハッシュが変わり、
「触っていない」ことの証明ができなくなる）。

---

## 8. テスト方法（Windows / 実API 非依存で検証する）

偽の `gemini_client` を **対象モジュールのロード前に** `sys.modules` へ注入して payload を捕捉する。
**`ppt_translator/tests/test_ppt_translation_20260812_01.py`（95項目）がそのまま雛形になる。
新規に書き起こさずコピーして差分を当てるのが速い。**

`ppt_translation` と `word_translation` は「**run 単位で書式を保持して翻訳する**」という
設計思想が同じなので、5ツールの中で**いちばん流用が効く**。

### 検証環境について

| ライブラリ | Linuxコンテナ | 対応 |
|---|---|---|
| `python-docx` | **`pip install python-docx` で入る見込み**（`python-pptx` は 1.0.2 で動作確認済み。同じ lxml ベース） | 本物を使う |
| `requests` | 導入済み | そのまま |
| `tkinter` | **入らない**（apt必須） | `sys.modules` へスタブを注入する |

`python-docx` が本物で動けば、**合成DOCXを実際に生成して、翻訳文の書き戻しまで
エンドツーエンドで検証できる**（AI呼び出しだけ偽物に差し替える）。

### 検証すべき項目

- payload形状 / `model` が明示的に渡るか / `temperature` が `generationConfig` に camelCase で載るか
- **`safetySettings` が4カテゴリ分そのまま載るか**
- **`response.parts` が読めるか（空応答時に `[]` になり、`ValueError` → リトライになるか）**
- `response.text` が読めるか / payload が `json.dumps` 可能か
- 空・壊れたレスポンスで例外を投げないか
- リトライ・連続エラーのフェイルファストが従来どおり動くか（**元コードにある場合のみ**）
- 認証情報判定の4パターン（**プロキシURLのみ = 通る** が特に重要）
- 共通モジュール未配置時に「探索したパス」を含むエラーが出るか
- **`init_gemini()` がネットワークアクセスなしで完了するか**（`list_models` を消せている証拠）
  - `socket.socket` を差し替えて「ソケット生成したら失敗」にしてから `init_gemini()` を呼び、
    成功することで証明する。**先行2ツールで使った手がそのまま使える。**
- 共通モジュール探索が「2つ上が common」のレイアウトで正しく解決するか
  （移行元の「1つ上」レイアウトでも解決することも併せて確認するとよい）

### Word固有のエンドツーエンド検証（ここが今回の肝）

合成DOCX（見出し＋本文＋**表**＋**ヘッダー/フッター**、runごとにフォントサイズ・太字・色を設定）を
生成し、翻訳を適用したあとで次を確認する:

- 翻訳文が run に書き戻されていること
- **run単位の書式（`font.size` / `font.bold` / `font.color.rgb` / 段落のスタイル・配置）が
  翻訳前後で不変**であること
- 表のセルも翻訳対象として拾えていること
- 元コードがヘッダー/フッター・脚注を対象にしているなら、それも拾えていること

**Word固有の注意（着手時に現物で確認すること）:**

- **テキストボックス内の文字（`w:txbxContent`）は `python-docx` の標準API（`document.paragraphs` /
  `document.tables`）では辿れない。** 元コードがXMLを直接触って拾っているのか、そもそも対象外なのかを
  確認し、**現状の挙動をそのまま維持する**こと（移行のついでに対応範囲を広げない）。
- **日本語フォントの指定は、Wordでは `run.font.name` だけでは日本語文字に効かない**
  （`w:eastAsia` の設定が別途必要）。元コードがどう書いているかを確認し、**触らないこと**。
  仮に日本語フォントが効いていない既存不具合があっても、それは移行スコープ外（§9-(6)）。

**注意（先行ツールで実際に踏んだ失敗）**: 「出力ファイルが完全一致するはず」と決め打ちで
アサーションを書くと外れる。PDFでは墨消しの塗り矩形が増えるため座標の集合が一致せず、テストが
落ちた（実装は正しかった）。**DOCX も PPTX と同様に zip のタイムスタンプが毎回変わるため
バイト比較はできない。** run 単位のテキストと書式を抽出して比較すること。
**先に旧版が何を出力するかを実測し、その事実にテストを合わせること。**

### 変更範囲を客観的に示す（CHANGELOGの裏付けになる）

```bash
python3 - <<'EOF'
import ast, hashlib
def funcs(p):
    src = open(p, encoding='utf-8').read(); lines = src.splitlines()
    return {n.name: hashlib.md5("\n".join(lines[n.lineno-1:n.end_lineno]).encode()).hexdigest()[:8]
            for n in ast.walk(ast.parse(src))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
a = funcs('word_translation_20260306_01.py'); b = funcs('word_translation_YYYYMMDD_01.py')
print("未変更:", sorted(k for k in a if k in b and a[k] == b[k]))
print("変更  :", sorted(k for k in a if k in b and a[k] != b[k]))
print("削除  :", sorted(k for k in a if k not in b))
print("新規  :", sorted(k for k in b if k not in a))
EOF
```

**Word処理側の関数がすべて「未変更」に並ぶことを確認する。**
変更されてよいのは **`check_dependencies` / `init_gemini` / `translate_batch_gemini` の3つだけ**
（`pdf_translator` / `ppt_translation` でも全く同じ3つだった）。

さらに強い証拠として、**旧版と新版に同じ翻訳文を与えて出力を比較し、完全一致を確認する**。
`ppt_translation` ではこれができた（旧版に偽の `gemini_model` を差し込んで同じ訳文を返させ、
run単位のテキスト・書式・フォント名がすべて一致することを確認）。**強く推奨する。**

---

## 9. ハマりどころ（先行5ツールで実際に踏んだもの）

### (1) 【最重要】APIキー未設定ガードが全AI機能を止める

移行後は **`GEMINI_API_KEY` が空でも正常**な構成がありうる（プロキシ専用）。
ところが多くのツールには「APIキーが無ければ止める」ガードがある。放置すると全機能が死ぬ。

```python
def gemini_credentials_available():
    """直接呼び出しが遮断されていてもプロキシ経由なら成功しうるため、
    GEMINI_API_KEY / GEMINI_PROXY_URL のどちらか一方でもあれば通す。"""
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_PROXY_URL"))
```

**作業手順**: `grep -n "GEMINI_API_KEY"` を必ず実行し、ヒットした全箇所を確認する。
新規に作る／既存の bat・README にも同じ配慮が要る。

### (2) 【今回いちばん時間を無駄にしやすい】付随ファイルは着手前に全部そろえてもらう

`pdf_translator` のセッションでは `run_pdf_translator.bat` がアップロードされておらず、
仕様の説明文から**バッチを丸ごと再構成してしまった**。その直後に実物が届いたため、再構成は破棄して
実物へ最小パッチを当て直す羽目になった（作業の手戻り）。

**今回は専用フォルダが既に存在するぶん、付随ファイルがある可能性が高い。着手前に必ず
ユーザーへ確認すること**（§11）。

### (3) `gemini_client` の import は `try/except` にする

無条件 import にすると、共通モジュール未配置時に**ツール自体が起動できなくなる**。
`try/except` で受けて、実際にAI呼び出しが行われた時点で「探索したパス」「元のエラー」
「`GEMINI_COMMON_DIR` で指定できること」を含むエラーを出す。

ただし `word_translation` は**全機能がAI翻訳**のはずなので、`check_dependencies()` / `init_gemini()` の
時点で分かりやすく案内して終了させてよい（`excel_translation` / `pdf_translator` /
`ppt_translation` でも同じ判断をした）。「起動だけはできるが何もできない」より親切。

### (4) `model` は必ず明示的に渡す

`generate_advanced(payload, model=model)` の `model` を省略すると共通モジュール側の既定モデルに落ちる。
UI表示と実際のモデルが食い違う silent failure の原因になる。

### (5) 設計提案書・行番号を鵜呑みにしない

`excel_translation` では、事前の設計提案書が「`from google.genai import types` が L21 にある」と
書いていたが、**実物は旧SDK `google.generativeai` で、そんな行は存在しなかった**。

**必ず対象ファイルを自分で読み、grepで実数を数えてから着手すること。**
**本資料の §5 は現物を見ずに書いているので、特に注意する（§0）。**

### (6) 移行と無関係な既存不具合を「移行のせい」と誤診しない

切り分け手順:

1. **AIが翻訳文を返しているか**を見る。返っていれば通信・レスポンス解析は成功しており、移行のコアは動いている。
2. 疑わしい関数が移行前後で同一かをハッシュで確認する（§8 の AST 比較スクリプト）。

先行ツールで実際にあった「移行スコープ外なので触らないもの」の例:

- チャンクが例外で失われたとき `[""] * batch_size` で埋めるため、最終チャンクだと件数が合わなくなりうる
- 進捗ウィンドウのクラス名が実態と合っていない（`ppt_translation` の `WordProgressWindow`）
- 出力ファイル名の付き方が他ツールと不揃い
  （**既存の出力名が変わるとユーザーの運用に影響するので、依頼が無い限り変えない**）
- 素の `except:`

**word_translation でも同種のものが見つかるはずだが、移行のついでに直さないこと。**
見つけたら CHANGELOG か納品メッセージに「既知の挙動・移行スコープ外」として記録しておく。
実機で報告されたときに「移行のせいではない」と即答できる。

---

## 10. 納品

- **このツール群はローカルではGitを使わない運用**。ユーザーはファイルをダウンロードして差し替える。
  そのため、**リポジトリへのpushとは別に、成果物ファイルを個別に送ること**。
  送るのは「新しい／変更した全ファイル」（スクリプト本体＋作成・更新した付随ファイル）。
- バージョン管理はファイル名の日付＋連番。**過去リビジョンは削除せず残す。**
- **実機検証できていないことは必ず明記する**。特に「プロキシ経由で実際に応答が返るところは未確認」は
  毎回書く（Linuxコンテナからは共通モジュールにもプロキシにも到達できないため）。
- 実機で確認してほしい項目を箇条書きで残す。`word_translation` なら最低限:
  1. `PythonScripts\word\word_translator\` にファイルを配置
  2. `GEMINI_API_KEY` / `GEMINI_PROXY_URL` 設定後、**コマンドプロンプトを開き直してから**起動
  3. **起動できること**（移行前は初期化で落ちていた見込みの点）
  4. 実際にDOCXを翻訳し、ログと画面に `[gemini_client]` のログが出たうえで翻訳結果が返ること
  5. フォント・色・配置・表・ヘッダー/フッターの書式が従来どおり保持されていること
     （Word処理側は未変更なので影響しない想定）
  6. 初回バッチだけ遅くなる場合があるが仕様であること（§5-4）

---

## 11. 着手前にユーザーへ確認すること

1. **`PythonScripts\word\word_translator\` に、起動バッチ・`requirements.txt`・`README.md`・
   `CHANGELOG.md` が既にあるか。** あるなら**実物をすべてアップロードしてもらう**
   （§9-(2) の手戻りを防ぐ。専用フォルダがある以上、ある可能性は高い）。
   無ければ新規に作る（§6）。
2. **起動用バッチを新規に作ってよいか**（無い場合）。`ppt_translator` と同じ「初回のみvenv作成＋
   `pip install`、最新ファイルを自動起動」方式でよいか。不要なら作らない。
3. **フォルダ名・ファイル名の接頭辞を今のまま（`word_translator` / `word_translation`）で
   維持してよいか。** 統一したくなるが、**起動用batや運用に影響するので勝手に変えない。**

---

## 12. 未確定・要判断

- **「直接接続の復活お知らせ」機能を入れるか。**
  TYPE A（`outlook_total_organizer`）にのみ実装済み。複数ツールに入れると同じ日に何度も
  ポップアップが出るため、集約方針が未決のまま `excel_translation` / `pdf_translator` /
  `ppt_translation` では**見送った**。`word_translation` でも同様に見送るのが自然。
- `GEMINI_RETRY_DIRECT_AFTER_SECONDS` は 2026-08-12 にユーザー判断で 86400（1日）へ変更する運用に
  なった。この環境変数は `gemini_client.py` が読むため**全ツール共通に効く**。
  `word_translation` 側で個別に変えることはできない。
- 自動モデル検出を外したことで、将来モデル名が変わったときに**手で更新が必要**になる。
  環境変数 `GEMINI_MODEL` で上書きできるようにしてあるので実運用上は困らないはずだが、
  READMEに書いておくこと。
- **【重要・6ツール目の完了後に必ず検討する】**
  これで `gemini_client.py` を使うツールが6つになる。モデル名の一括変更や「復活お知らせ」の集約を
  各ツールで個別に抱えるのは限界に近い。**共通モジュール側でまとめて面倒を見る設計**へ移す時期。
  必要になったら `gemini-common-tools` 側で議論すること（本ツールのスコープ外）。

---

## 13. ユーザーとのコミュニケーションについて

- **越智さんはGitの用語に不慣れ**。`git push` / PR / マージといった語をそのまま使わず、
  **必要なら例え話で補足する**。実際に「清書版のノート（main）と下書きノート（ブランチ）」
  「下書きを清書版に入れていいですかの申請書（PR）」という説明で通じた。
- PRの作成・マージは**明示的に依頼されてから**行う。勝手に作らない。
- 説明は結論から。日本語で。
