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

**本資料の §0 / §5 は、対象ファイル（407行・CRLF）を実際に読み、AST比較を実行して書いている。
行番号は `word_translation_20260306_01.py` 時点の実測値。**

---

## 0. 結論から: 「PPTの移行差分をほぼ流用できる。ただしWord版は"祖先"なので機能が少ない」

### 0-1. 系譜（実測で確定した事実）

本セッションで `word_translation_20260306_01.py` と `ppt_translation_20260309_03.py` の
AST比較を実行した結果:

| 関数・クラス | word と ppt(旧版) の比較 |
|---|---|
| **`init_gemini`** | **完全一致（39行）** ← 最重要 |
| `WordProgressWindow`（`__init__` / `update_progress` / `_update_gui` / `close`） | **完全一致（58行）** |
| `is_translatable` | **完全一致（15行）** |
| `check_dependencies` | 18行中4行だけ違う（`HAS_DOCX`/`python-docx` か `HAS_PPTX`/`python-pptx` か） |
| `select_file` | 53行中8行だけ違う（ダイアログの文言・拡張子） |
| `translate_batch_gemini` | **word 59行 / ppt 69行。大きく違う（§0-2）** |
| `translate_super_fast_parallel` | **word 31行 / ppt 56行。大きく違う（§0-2）** |
| `get_logger` | **wordには存在しない** |

**`ppt_translation` の進捗クラスが `WordProgressWindow` という名前のままなのは、
このWord版からコードごと持っていったから**である（完全一致で裏が取れた）。
日付も `word 2026-03-06` → `ppt 2026-03-09` の3日差。**Word版がこの系統の祖先で確定。**

### 0-2. 【重要】祖先ゆえに、PPT版にある機能がWord版には無い

`ppt_translation_20260309_03.py` は「VERSION 2026.0309.03」で**リトライ・ロギング等をまとめて
追加した版**だった。Word版はその手前なので、次が**すべて存在しない**（grepで実数確認済み）。

| PPT版にあってWord版に無いもの | grep結果 |
|---|---|
| ロギング（`get_logger` / `translation_debug.log`） | `logging` 0件 / `logger` 0件 |
| 3回リトライ・3秒待機 | `for attempt in range(1, 4)` 無し（例外時は `print` して原文を返すだけ） |
| フェイルファスト（3バッチ連続エラーで強制中断） | `abort_event` 0件 |
| 進捗コールバック（バッチごとのプログレスバー更新） | `progress_callback` 0件 |
| **`request_options={"timeout": 40}`** | **0件（＝そもそも存在しない）** |
| ファイルロックの事前検知（WinError 32対策） | 読み込み元・出力先の事前チェック無し |
| `traceback` によるエラー詳細出力 | `traceback` 0件 |
| 先頭のバージョン記載 docstring | 無し（1行目がいきなり `import tkinter`） |

**これらを移行のついでに足さないこと（スコープ外）。** 足すなら別作業としてユーザーに提案し、
依頼を受けてから行う（§12）。移行と機能追加を混ぜると、実機で不具合が出たときに
「移行のせいか、追加機能のせいか」が切り分けられなくなる。

### 0-3. 外さないでほしい点

| # | 箇所 | 何が起きるか |
|---|---|---|
| 1 | `genai.list_models()`（**L61**） | **起動時にネットワークを叩くため、遮断下では初期化に失敗して `sys.exit(1)`（L380-381）。ツールが立ち上がらない。** `init_gemini` はPPT版と完全一致なので、PPT版と全く同じ症状になる（実機で確認済みの事象） |
| 2 | `response.parts`（**L137**） | シムが `.parts` を持たないと `AttributeError` → **例外に落ちて原文が返る（＝翻訳されない）**。PPT版と挙動が違う点に注意（§5-2） |
| 3 | `safety_settings`（**L122-127**） | payloadへ載せないと `BLOCK_NONE` 指定が消え、内容によっては応答が空になる |
| 4 | 付随ファイル | **`word_translator` という専用フォルダが既にある**ため、起動batや `requirements.txt` が既存の可能性がある。**着手前に必ず確認**（§6・§11） |
| 5 | 元ファイルの体裁 | **CRLF改行**、かつ**72行に行末空白**がある。置換時の扱いを誤ると全関数のハッシュが変わり「触っていない」証明ができなくなる（§7・改行コードの節） |

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
  Wordツールとは「run単位で書式を保持する」設計思想が同じで、しかも**同じコードの子孫**なので、
  5ツールの中で**いちばん近い前例**。
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
並列処理・進捗表示のロジックは**一切変更しないで済む**。

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

## 5. word_translation の移行対象マップ（実測。行番号は `_20260306_01` 時点）

`ppt_translation` で実際に変更が必要だったのは **`check_dependencies` / `init_gemini` /
`translate_batch_gemini` の3関数だけ**だった（`pdf_translator` でも同じ3つ）。
**word_translation でも同じ3つになる見込み。**

| 行 | 内容 | 対応 |
|---|---|---|
| L13 | `import google.generativeai as genai` | 削除 |
| L12-16 | `HAS_GEMINI` | 共通モジュールを読めたかどうかへ意味を変更 |
| L27-28 | `check_dependencies()` の `google-generativeai` | 共通モジュールのチェックへ差し替え（`HAS_DOCX` はそのまま残す） |
| L44 | `gemini_model = None`（グローバル） | シムのクライアントを入れる（名前は `gemini_client`。他5ツールと揃える） |
| L49-54 | `GEMINI_API_KEY` 必須ガード | `gemini_credentials_available()` へ（§9-(1)） |
| L57 | `genai.configure(api_key=api_key)` | 削除 |
| **L59-80** | **`genai.list_models()` による自動モデル検出** | **削除。固定モデル名へ（最重要・§5-1）** |
| L104 | `if not gemini_model` | `if not gemini_client` へ |
| L122-127 | `safety_settings`（BLOCK_NONE ×4） | **payload の `safetySettings` へ載せる（§5-3）** |
| L129-133 | `gemini_model.generate_content(...)` | シム経由へ置換（§5-4） |
| L131 | `genai.types.GenerationConfig(temperature=0.1)` | ローカルの config クラス（`_GeminiGenerateConfig`）へ |
| **L137-138** | **`if not response.parts: return texts`** | **シムに `.parts` を持たせる（§5-2）** |
| L140 | `response.text.strip()` | 変更不要（シム対応済み） |

- **`request_options` は存在しない**（grep 0件）。PPT/PDF版では削除対象だったが、**今回は削除する
  ものが無い**。ただし挙動としては「SDK既定のタイムアウト」から「`gemini_client.py` 側の固定値
  （直接15秒 / プロキシ60秒）」へ変わるので、CHANGELOGには挙動差として書く（§5-5）。
- Grounding（`google_search` / `tools=`）は**未使用**、`response_schema` も**未使用**、
  `system_instruction` も**未使用**（プロンプト本文に指示を書き込む方式）。
- `import os`（L3）/ `import sys`（L4）は既にあるため、**シムのために追加するimportは無い。**
- **`translate_batch_gemini` のシグネチャはPPT版と違う。** word は
  `translate_batch_gemini(texts, target_language="Japanese")` で、**戻り値はリスト単体**
  （PPT版は `(texts, batch_idx, logger)` を取り `(results, is_error)` のタプルを返す）。
  **PPT版の関数をそのまま貼り付けないこと。** word のシグネチャ・戻り値を維持する。

**Word処理側（`translate_word_document_thread` の `doc.paragraphs` / `doc.tables` 走査、
run単位の書き戻し、`WordProgressWindow`、`select_file`）は一切触らないこと。**

### 5-1. 【最重要】`genai.list_models()` で起動できなくなる

```python
# L56-80（現状）
genai.configure(api_key=api_key)
available_models = []
for m in genai.list_models():                    # ← ネットワークアクセス
    if 'generateContent' in m.supported_generation_methods:
        available_models.append(m.name)
...
gemini_model = genai.GenerativeModel(target_model_name)
```

`init_gemini()` は `__main__` から呼ばれ、`False` を返すと `sys.exit(1)`（L380-381）。
**遮断下では `list_models()` が例外を投げ、`except`（L82）に落ちて「API初期化エラー」ダイアログ →
即終了する。** つまりこのツールは移行しない限り起動すらできない。

**この `init_gemini` は `ppt_translation_20260309_03.py` の同名関数と1文字も違わない（39行・完全一致）。**
PPT版は実機で「移行前は起動できず、移行後は起動できる」ことが確認済みなので、Word版も同じになる。

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

### 5-2. 【PPT版と挙動が違う】`response.parts` が空のとき「原文を返す」

```python
# L137-138（現状）
if not response.parts:
    return texts
```

PPT版は `raise ValueError("Empty response from API")` してリトライへ回していたが、
**Word版はリトライ機構が無いので、その場で原文を返して終わる**（＝そのバッチは翻訳されない）。

シムに `.parts` を持たせれば、空応答のとき `[]` が返るので、**この「空なら原文を返す」という
既存の挙動がそのまま保たれる**。`ppt_translation_20260812_01.py` の `_CommonGeminiResponse` は
既にこの対応が入っている。

**ここでPPT版のリトライ挙動に「揃えたく」なるが、やらないこと（§0-2・スコープ外）。**

### 5-3. `safety_settings` を payload へ載せる

L122-127 の `safety_settings` は既にREST形式の dict のリスト（`category` / `threshold`）なので、
**そのまま `payload["safetySettings"]` に入れればよい**。載せ忘れると `BLOCK_NONE` 指定が消え、
資料の内容によっては応答が空になる。Word版は空応答時に原文を返すだけなので、
**「一部の段落だけ翻訳されていない」という、さらに気づきにくい症状**になる。

### 5-4. 呼び出し側（L129-133）の置換後

```python
        # 旧: gemini_model.generate_content(prompt,
        #         generation_config=genai.types.GenerationConfig(temperature=0.1),
        #         safety_settings=safety_settings)
        # 新: 共通モジュール(gemini_client.py)経由の互換シムで同じ内容を送る。
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=prompt,
            config=_GeminiGenerateConfig(temperature=0.1, safety_settings=safety_settings),
        )
```

### 5-5. タイムアウトの挙動差

Word版は元々タイムアウトを指定していない（`request_options` 無し）ので、旧SDKの既定に従っていた。
移行後は `gemini_client.py` 側の固定値（**直接15秒 / プロキシ60秒**）になる。
呼び出し側から指定する口は無い。**CHANGELOGに挙動差として明記する。**

遮断下では**初回のバッチだけは直接呼び出しの15秒タイムアウトを待つぶん遅くなる**。
一度失敗すると `.gemini_direct_disabled_until` に記録され、以降は直接呼び出しをスキップして
プロキシ直行になる。**これは仕様どおりの挙動で、バグではない。**
実機で「最初だけ遅い」と報告されても慌てないこと。

**ただしWord版には注意点がある。** リトライ機構が無いため、初回バッチが15秒で失敗した場合、
**そのバッチは即座に原文のまま返る**（PPT版なら3回リトライして拾えていた）。
これは移行で新たに生じるリスクではなく元からの構造だが、実機で「最初の10項目だけ英語のまま」
という症状が出たらこれを疑う。**気になるならリトライ追加を別作業として提案する**（§12）。

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
- **既知の制限**（§9-(6) の一覧。特に「ヘッダー/フッター・脚注・テキストボックスは翻訳対象外」は
  ユーザーが実機で気づきやすいので必ず書く）

### (4) `CHANGELOG.md`

`ppt_translator/CHANGELOG.md` の書式（`## [YYYYMMDD_NN] - YYYY-MM-DD` + 追加ファイル/更新ファイル）に
合わせる。新規作成になる場合、**元ファイルには履歴 docstring が無い**ので、`[20260306_01]` の
エントリは「移行前の最終版」として、コードから読み取れる仕様（run単位の書式保持翻訳、
段落＋表を対象、10件バッチ×最大3並列、出力は `_gemini_japanese.docx`）を簡潔に書けばよい。

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

### 【必読】改行コードと行末空白（実測値）

`word_translation_20260306_01.py` は次のとおり。**そのまま維持して書き出すこと。**

- **CRLF改行**（406行すべて `\r\n`）
- **行末に空白が残っている行が72行ある**（L31, L38, L51, L55, L58, L64, L74, L78, L90, … など）

`ppt_translation` の移行では、この2点で実際につまずいた。教訓:

1. Pythonで置換するなら `open(..., encoding="utf-8", newline="")` で読み、
   `open(..., encoding="utf-8", newline="\r\n")` で書く。
2. 置換対象の文字列を素朴に書くと、**行末空白のせいでマッチしない**。
   行末の空白・タブを許容する正規表現に組み立ててから照合するとよい:

   ```python
   pattern = re.compile("[ \t]*\n".join(re.escape(l.rstrip()) for l in old.split("\n")))
   ```

3. **行末空白を一括除去してはいけない。** 未変更のはずの関数までハッシュが変わり、
   §8 のAST比較で「触っていない」ことを証明できなくなる。

---

## 8. テスト方法（Windows / 実API 非依存で検証する）

偽の `gemini_client` を **対象モジュールのロード前に** `sys.modules` へ注入して payload を捕捉する。
**`ppt_translator/tests/test_ppt_translation_20260812_01.py`（95項目）がそのまま雛形になる。
新規に書き起こさずコピーして差分を当てるのが速い。**

`ppt_translation` と `word_translation` は「**run 単位で書式を保持して翻訳する**」という
設計が同じ（しかも同じコードの子孫）なので、5ツールの中で**いちばん流用が効く**。

### 検証環境について（本セッションで実測済み）

| ライブラリ | Linuxコンテナ | 対応 |
|---|---|---|
| `python-docx` | **`pip install python-docx` で入る。動作確認済み（1.2.0）** | 本物を使える |
| `requests` | 導入済み | そのまま |
| `tkinter` | **入らない**（apt必須） | `sys.modules` へスタブを注入する |

`python-docx` が本物で動くのは大きい。**合成DOCXを実際に生成して、翻訳文の書き戻しまで
エンドツーエンドで検証できる**（AI呼び出しだけ偽物に差し替える）。

### 雛形を流用するときに直す必要がある箇所

PPT版のテストをコピーしたあと、**word版のシグネチャ差に合わせて必ず直すこと**（§5）。

- `translate_batch_gemini(texts, target_language)` … **引数は2つ。戻り値はリスト単体**
  （PPT版の `out, is_error = ...` というタプル受けはそのままでは動かない）
- `translate_super_fast_parallel(all_texts, target_language, max_workers)` …
  **`progress_callback` / `logger` 引数は無い**
- **リトライ・フェイルファストのテストは丸ごと削除する**（word版に機能が無いため）。
  代わりに「**空応答・通信失敗のとき、リトライせず1回で原文を返す**」ことをテストする
  （＝既存挙動が保たれている証明になる）
- `translate_ppt_document_thread` → `translate_word_document_thread`
- 出力ファイル名 `_gemini_japanese.pptx` → `_gemini_japanese.docx`

### 検証すべき項目

- payload形状 / `model` が明示的に渡るか / `temperature: 0.1` が `generationConfig` に camelCase で載るか
- **`safetySettings` が4カテゴリ分そのまま載るか**
- **`response.parts` が読めるか（空応答時に `[]` になり、原文がそのまま返るか）**
- `response.text` が読めるか / payload が `json.dumps` 可能か
- 空・壊れたレスポンスで例外を投げないか
- 認証情報判定の4パターン（**プロキシURLのみ = 通る** が特に重要）
- 共通モジュール未配置時に「探索したパス」を含むエラーが出るか
- **`init_gemini()` がネットワークアクセスなしで完了するか**（`list_models` を消せている証拠）
  - `socket.socket` を差し替えて「ソケット生成したら失敗」にしてから `init_gemini()` を呼び、
    成功することで証明する。**先行2ツールで使った手がそのまま使える。**
- 共通モジュール探索が「2つ上が common」のレイアウトで正しく解決するか

### Word固有のエンドツーエンド検証（ここが今回の肝）

合成DOCX（見出し＋本文（同一段落に書式違いの複数run）＋**表**、runごとにフォントサイズ・太字・色を
設定）を生成し、翻訳を適用したあとで次を確認する:

- 翻訳文が run に書き戻されていること
- **run単位の書式（`font.size` / `font.bold` / `font.color.rgb` / 段落の `alignment`・`style`）が
  翻訳前後で不変**であること
- **表のセルも翻訳対象として拾えていること**（`doc.tables` 経路）
- 日本語指定時に `run.font.name` が `游ゴシック` になること（既存仕様）
- `is_translatable` で除外されるもの（2文字以下・記号・数字のみ）が原文のまま残ること

**Word固有の注意（実測で確認済み。仕様として維持すること）:**

- **ヘッダー/フッター・脚注・テキストボックス内の文字は翻訳対象外。**
  `translate_word_document_thread` は `doc.paragraphs` と `doc.tables` しか見ていない
  （`sections` / `header` / `footer` はgrep 0件）。**対応範囲を移行のついでに広げないこと。**
  READMEの「既知の制限」に明記して、実機で気づかれたときに即答できるようにする。
- **Wordの日本語フォント指定は `run.font.name` だけでは日本語文字に効かない**
  （`w:eastAsia` の設定が別途必要）。元コードは `run.font.name = '游ゴシック'` のみ（L294）。
  **これは既存の挙動なので触らないこと。** 実機で「フォントが変わらない」と言われても移行のせいではない。

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

**次の11個が「未変更」に並ぶことを確認する**（word版の全定義から、変更してよい3つを除いたもの）:
`WordProgressWindow` / `__init__` / `_update_gui` / `close` / `update_progress` /
`is_translatable` / `translate_super_fast_parallel` / `translate_chunk` /
`translate_word_document_thread` / `select_file` / `start_translation`

変更されてよいのは **`check_dependencies` / `init_gemini` / `translate_batch_gemini` の3つだけ**。

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
`word_translation` では **L49-54（ガード本体）が対象**。新規に作る／既存の bat・README にも
同じ配慮が要る。

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

ただし `word_translation` は**全機能がAI翻訳**なので、`check_dependencies()` / `init_gemini()` の
時点で分かりやすく案内して終了させてよい（`excel_translation` / `pdf_translator` /
`ppt_translation` でも同じ判断をした）。「起動だけはできるが何もできない」より親切。

### (4) `model` は必ず明示的に渡す

`generate_advanced(payload, model=model)` の `model` を省略すると共通モジュール側の既定モデルに落ちる。
UI表示と実際のモデルが食い違う silent failure の原因になる。

### (5) 設計提案書・行番号を鵜呑みにしない

`excel_translation` では、事前の設計提案書が「`from google.genai import types` が L21 にある」と
書いていたが、**実物は旧SDK `google.generativeai` で、そんな行は存在しなかった**。

本資料の §5 の行番号は `_20260306_01` の**実測値**だが、それでも
**着手時に必ず現物を開いて確認すること。**

### (6) 移行と無関係な既存不具合を「移行のせい」と誤診しない

切り分け手順:

1. **AIが翻訳文を返しているか**を見る。返っていれば通信・レスポンス解析は成功しており、移行のコアは動いている。
2. 疑わしい関数が移行前後で同一かをハッシュで確認する（§8 の AST 比較スクリプト）。

`word_translation` に元からある挙動で、**移行スコープ外なので触らないもの**（実測で確認済み）:

- **リトライが無い**（L157-160）… 例外時は `print` して原文を返すだけ。1回失敗したらそのバッチは終わり。
- **ロギングが無い**… `translation_debug.log` は出ない。エラーはコンソールへ `print` されるだけで、
  batから起動していると窓が閉じて見えないことがある。
- **進捗バーがほぼ動かない**（L282-296）… 翻訳中の更新が無く、`0 → 完了` の2段階だけ。
  長い文書では「固まったように見える」。**PPT版で解消済みの欠陥が、Word版には残っている。**
- **フェイルファストが無い**… API障害時も全バッチにリクエストを投げ続ける。
- `translate_super_fast_parallel()`（L189-190）… チャンクが例外で失われたとき `[""] * batch_size` で
  埋めるため、最終チャンクだと翻訳結果の件数が合わなくなりうる。
- **ファイルロックの事前検知が無い**… 出力先が開いていると、数分の翻訳が終わった後の保存時に
  初めてエラーになる（L298-303 で保存時のみ捕捉）。読み込み元のチェックも無い。
- `select_file`（L321）… `filetypes` に `*.doc` が含まれているが、**`python-docx` は旧形式 `.doc` を
  開けない**ため、選ぶとエラーになる。
- 出力ファイル名（L257-258）… `target_language.split()[0].lower()` を使うため
  `_gemini_japanese.docx` になる（`pdf_translator` の `_ja.pdf` のような2文字コードではない）。
  **統一したくなるが、既存の出力名が変わるとユーザーの運用に影響するので、依頼が無い限り変えない。**
- ヘッダー/フッター・脚注・テキストボックスが翻訳対象外（§8）。
- 素の `except:`（L205 / L244 / L248）。

これらは**実機で報告されたときに「移行のせいではない」と即答できるよう**記録している。
**直したくなるが、移行と混ぜないこと。** 提案するなら §12 を参照。

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
  3. **起動できること**（移行前は初期化で落ちていた点。ここが今回いちばん重要）
  4. 実際にDOCXを翻訳し、画面に `[gemini_client]` のログが出たうえで翻訳結果が返ること
     （**Word版はログファイルを作らない**ので、確認はコンソール表示のみ）
  5. フォント・色・配置・表の書式が従来どおり保持されていること（Word処理側は未変更なので影響しない想定）
  6. 初回バッチだけ遅くなる場合があるが仕様であること（§5-5）
  7. **進捗バーが途中で動かないのは元からの挙動**であること（§9-(6)）

---

## 11. 着手前にユーザーへ確認すること

1. **`PythonScripts\word\word_translator\` に、起動バッチ・`requirements.txt`・`README.md`・
   `CHANGELOG.md` が既にあるか。** あるなら**実物をすべてアップロードしてもらう**
   （§9-(2) の手戻りを防ぐ。専用フォルダがある以上、ある可能性は高い）。
   無ければ新規に作る（§6）。
2. **起動用バッチを新規に作ってよいか**（無い場合）。`ppt_translator` と同じ「初回のみvenv作成＋
   `pip install`、最新ファイルを自動起動」方式でよいか。不要なら作らない。
3. **今回は「Geminiプロキシ対応だけ」に絞ってよいか。** Word版にはPPT版で追加済みの
   リトライ・ロギング・進捗表示・フェイルファストが無い（§0-2）。**同時にやると切り分けが
   できなくなるので、まず移行だけを完了させ、機能追加は別作業にすることを勧める。**
   ただしユーザーが「ついでに揃えてほしい」と言うなら、それは判断として尊重する。

---

## 12. 未確定・要判断

- **【今回の目玉】Word版へPPT版の改善を逆輸入するか。**
  Word版は祖先なので、PPT版が持つ「3回リトライ・ロギング・進捗コールバック・フェイルファスト・
  ファイルロック事前検知」が無い（§0-2・§9-(6)）。移行後の次の一手として**別バージョン
  （`word_translation_YYYYMMDD_02.py` など）で揃える**のが自然。
  **移行と同時にやらないこと**（実機で問題が出たとき原因の切り分けができなくなる）。
  移行完了時に「こういう差分があります。揃えますか？」と提案するとよい。
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
