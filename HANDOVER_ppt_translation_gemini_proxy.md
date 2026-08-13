# 引継ぎ: ppt_translation の Gemini APIプロキシ対応（TYPE C）

2026-08-12 作成。`outlook_total_organizer`（TYPE A）・`excel_translation`・`pdf_translator`（TYPE C、
**実機で動作確認済み・PR #7 作成済み**）を同じ方式へ移行した実作業から得た知見をまとめたもの。
**「先に読むと事故を防げること」を優先して書いてある。**

対象（移行元）: `C:\Users\nx023836\Documents\PythonScripts\excel\ppt_translation_20260309_03.py`
新しい置き場所: `C:\Users\nx023836\Documents\PythonScripts\Powerpoint\ppt_translator\`
新ファイル名: `ppt_translation_20260812_01.py`（作業日が変わる場合は当日の日付にすること）

**この資料の使い方**: 新しいClaude Codeセッションを開き、この資料と `ppt_translation_20260309_03.py`
をアップロードして作業を依頼する。この資料は `my-claude-code` リポジトリのルートにも置いてあるため、
セッションからはリポジトリを読むだけでも参照できる。

---

## 0. 結論から: 今回は「pdf_translator の移行をほぼそのまま流用できる」

**Gemini呼び出し部分は pdf_translator の旧版とコードが実質同一である。** 本セッションで
AST比較を実行して確認した実測結果:

| 関数 | ppt_translation_20260309_03 と pdf_translator_20260722_08 の比較 |
|---|---|
| `translate_batch_gemini` | **完全一致**（69行） |
| `translate_super_fast_parallel` | **完全一致**（56行） |
| `is_translatable` | **完全一致**（15行） |
| `init_gemini` | 39行中 **docstringの1行だけ**違う（`（環境変数 GEMINI_API_KEY を使用、...）`の有無） |
| `get_logger` | 13行中 **1行だけ**違う（`"PPT_Translation"` / `"PDF_Translation"`） |
| `check_dependencies` | 18行中 **2行だけ**違う（`HAS_PPTX`/`python-pptx` か `HAS_PYMUPDF`/`PyMuPDF` か） |

つまり **`pdf_translator_20260812_01.py` の移行差分を、そのまま当てれば終わる**。
シムは1文字も変えずにコピーできる（`.parts` と `safetySettings` の対応も込みで既に入っている）。

そのうえで、外さないでほしい点は次の5つ。

| # | 箇所 | 何が起きるか |
|---|---|---|
| 1 | `genai.list_models()`（L95） | **起動時にネットワークを叩くため、遮断下では初期化に失敗して `sys.exit(1)`。ツールが立ち上がらない** |
| 2 | `response.parts`（L175） | シムが `.parts` を持たないと `AttributeError` → 全バッチが3回リトライ後に失敗 |
| 3 | `safety_settings`（L155-160） | payloadへ載せないと `BLOCK_NONE` 指定が消え、内容によっては応答が空になる |
| 4 | `request_options={"timeout": 40}`（L171） | 共通モジュールに同等機能なし。削除して挙動差を記録する |
| 5 | 付随ファイルが**1つも存在しない** | `requirements.txt` / `README.md` / `CHANGELOG.md` / 起動用batを新規に作る必要がある（§6） |

---

## 1. 背景

会社PCからGemini APIへの直接アクセスが遮断された（2026-08-10頃）。対策として、共通モジュール
`gemini_client.py` の `generate_advanced()` を経由し、直接呼び出しが失敗したら自宅PCの
プロキシへ自動フォールバックする仕組みへ移行している。

移行済みのツール:

- `rtocs_organizer`
- `analog_ic_se_strategy_organizer`
- `outlook_total_organizer` … 2026-08-12 完了（TYPE A）
- `excel_translation` … 2026-08-12 完了。**実機で動作確認済み・mainへマージ済み**
- `pdf_translator` … 2026-08-12 完了。**実機で動作確認済み・PR #7 作成済み**

今回の対象: **ppt_translation**（TYPE C = Git未管理）

### 系譜について（知っておくと理解が早い）

`pdf_translator` は、もともと **この `ppt_translation_20260309_03.py` を土台に作られた**
（`pdf_translator` の docstring に「ppt_translation_20260309_03.py の設計を踏襲」と明記されている）。
そのためGemini呼び出し・進捗表示・ロギングまわりが瓜二つになっている。今回はいわば
**親（PPT）に、子（PDF）で先に済ませた改修を戻す**作業にあたる。

---

## 2. 参照資料（推測で書かず、必ず実物を読むこと）

- **最優先**: `my-claude-code` の `pdf_translator/pdf_translator_20260812_01.py`
  … 移行後の完成形。シム（**L215〜L408**）はここから丸ごとコピーしてよい。
- `my-claude-code` の `pdf_translator/pdf_translator_20260722_08.py` … 移行前。差分の取り方の参考。
- `my-claude-code` の `pdf_translator/tests/test_pdf_translator_20260812_01.py`
  … 75項目のテスト。**新規に書き起こさずコピーして差分を当てるのが速い。**
- `my-claude-code` の `pdf_translator/CHANGELOG.md` の `[20260812_01]` … 記載フォーマットの見本。
- 全体設計: `gemini-common-tools` リポジトリの `GEMINI_MIGRATION_HANDOVER.md`
- 共通モジュール本体: 同リポジトリの `gemini_client.py`。公開リポジトリなので匿名cloneで取得できる:
  `git clone --depth 1 https://github.com/ochi1216/gemini-common-tools`
  **payloadの送られ方（`_call_direct_advanced` / `_call_proxy_advanced`）を必ず自分の目で確認すること。**
  「プロキシは payload をそのまま透過し、`model` だけ `_gemini_model` フィールドに載せ替える」という
  事実を知らないと、`safetySettings` を載せてよいか判断できない。
- 前回の引継ぎ資料: `HANDOVER_pdf_translator_gemini_proxy.md`（本資料はこれの改訂版）

---

## 3. 移行の全体方針: 「互換シム」1つで置き換える

`genai` SDK の呼び出しを個別に全部書き換えてはいけない。`genai.Client` と同じインターフェースだけを
持つ薄い互換シムを1つ作り、**クライアント生成箇所だけ**を差し替える。

これにより、レスポンスを読む側（`response.text` を正規表現で解析して番号付きリストへ戻す処理）や、
リトライ・フェイルファスト・進捗表示のロジックは**一切変更しないで済む**。

**5ツールすべてでシムの形を揃えること。** 呼び出しの形は
`client.models.generate_content(model=..., contents=..., config=...)` に統一する。

---

## 4. Git環境の作り方（TYPE C 固有。ここを最初にやる）

リポジトリ: `ochi1216/my-claude-code`（セッション開始時にクローン済みのはず）

```bash
# 1. 指定された作業ブランチを作る（ブランチ名はセッション開始時に指示される）
git fetch origin main
git checkout -B claude/<指示されたブランチ名> origin/main

# 2. フォルダを作り、アップロードされた「現状のファイル」をそのまま置く
mkdir -p ppt_translator/tests
#   ppt_translation_20260309_03.py をコピー（付随ファイルは存在しないので、これ1つだけ）

# 3. ★重要★ ここで一度コミットする（＝移行前の基準点を作る）
git add ppt_translator && git commit -m "Add ppt_translation as-is (baseline before Gemini proxy migration)"
```

**手順3を必ず先に単独でコミットすること。** これをやっておくと、次のコミットの `diff` が
「移行で変えた箇所」だけになり、CHANGELOGに書く「変更関数」「未変更であることの証明」を
客観的に示せる。`pdf_translator` ではこれで「PDF処理側の27定義が旧版と完全一致」を証明できた。

そのうえで:

- 新ファイルは **`ppt_translation_20260812_01.py`**（作業日が変わるなら当日の日付に。
  **日付は必ず `date` コマンド等で確認して決める**）。`v` 記号は付けない。同日再リリースは `_02`。
- **旧版 `ppt_translation_20260309_03.py` は削除しない。** 併存させる（リポジトリの運用ルール）。
- フォルダ名は **`ppt_translator`**（＝実機の新しい置き場所に合わせる）。
  ファイル名の接頭辞は **`ppt_translation`** のまま（フォルダ名と接頭辞が違う点に注意。
  起動用batのワイルドカードを書くときに間違えやすい）。
- ルートの `README.md` にツール一覧の項目を1つ追記する（既存の書式に合わせる）。
- 最後に `git push -u origin <ブランチ名>`。PR作成とマージは**ユーザーから明示的に依頼されてから**行う。

---

## 5. ppt_translation の事前分析（本セッションで実施済み。ここが本題）

`ppt_translation_20260309_03.py` を通読して洗い出した移行対象。**行番号は `_20260309_03` 時点のもの。**

### 5-1. 移行対象マップ

| 行 | 内容 | 対応 |
|---|---|---|
| L32 | `import google.generativeai as genai` | 削除 |
| L31-35 | `HAS_GEMINI` | 共通モジュールを読めたかどうかへ意味を変更 |
| L46-47 | `check_dependencies()` の `google-generativeai` | 共通モジュールのチェックへ差し替え（`HAS_PPTX` はそのまま残す） |
| L63 | `gemini_model = None`（グローバル） | シムのクライアントを入れる（名前は `gemini_client`。他4ツールと揃える） |
| L83-88 | `GEMINI_API_KEY` 必須ガード | `gemini_credentials_available()` へ |
| L91 | `genai.configure(api_key=api_key)` | 削除 |
| **L93-114** | **`genai.list_models()` による自動モデル検出** | **削除。固定モデル名へ（最重要・§5-2）** |
| L138 | `if not gemini_model` | `if not gemini_client` へ |
| L155-160 | `safety_settings`（BLOCK_NONE ×4） | **payload の `safetySettings` へ載せる（§5-4）** |
| L167-172 | `gemini_model.generate_content(...)` | シム経由へ置換 |
| L169 | `genai.types.GenerationConfig(temperature=0.1)` | ローカルの config クラス（`_GeminiGenerateConfig`）へ |
| L171 | `request_options={"timeout": 40}` | **削除（同等機能なし・§5-5）** |
| **L175** | **`if not response.parts:`** | **シムに `.parts` を持たせる（§5-3）** |
| L179 | `response.text.strip()` | 変更不要（シム対応済み） |

Grounding（`google_search` / `tools=`）は**未使用**、`response_schema` も**未使用**、
`system_instruction` も**未使用**（プロンプト本文に指示を書き込む方式）。
`import os`（L20）/ `import sys`（L21）は既にあるため、シムのために追加するimportは無い。

**PowerPoint処理側（`translate_ppt_document_thread` のスライド走査・run単位の書き戻し・
`WordProgressWindow`・`select_file`）は一切触らないこと。**

### 5-2. 【最重要】`genai.list_models()` で起動できなくなる

```python
# L90-114（現状）
genai.configure(api_key=api_key)
available_models = []
for m in genai.list_models():                    # ← ネットワークアクセス
    if 'generateContent' in m.supported_generation_methods:
        available_models.append(m.name)
...
gemini_model = genai.GenerativeModel(target_model_name)
```

`init_gemini()` は `__main__` から呼ばれ、`False` を返すと `sys.exit(1)`（L495-496）。
**遮断下では `list_models()` が例外を投げ、`except` に落ちて「API初期化エラー」ダイアログ →
即終了する。** つまりこのツールは移行しない限り起動すらできない。`pdf_translator` と全く同じ
構図であり、実機でもそのとおりだった（移行後に起動できることを確認済み）。

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
ただし `gemini-2.5-flash` は他4ツールで実績があり、実害はまず無い。CHANGELOGに明記すること。

### 5-3. 【要注意】`response.parts` を見ている

```python
# L175-177
if not response.parts:
    if logger: logger.warning(...)
    raise ValueError("Empty response from API")
```

シムに `.parts` を持たせて解決する。空応答のとき `[]` を返せば、**元の
「空ならValueErrorでリトライ」という挙動がそのまま保たれる**（ここが大事）。
`pdf_translator_20260812_01.py` の `_CommonGeminiResponse` は既にこの対応が入っている。

### 5-4. `safety_settings` を payload へ載せる

L155-160 の `safety_settings` は既にREST形式の dict のリスト（`category` / `threshold`）なので、
**そのまま `payload["safetySettings"]` に入れればよい**。載せ忘れると `BLOCK_NONE` 指定が消え、
資料の内容によっては応答が空になり「一部バッチだけ翻訳されない」という切り分けにくい症状になる。

### 5-5. `request_options={"timeout": 40}` は等価な置き換えができない

共通モジュールのタイムアウトは `gemini_client.py` 側の固定値（**直接15秒 / プロキシ60秒**）で、
呼び出し側から指定する口が無い。**引数は削除し、CHANGELOGに挙動差として明記する。**

実害は小さい。理由: このツールは3回リトライ（3秒間隔）を自前で持っており、
`gemini_client` 側も「直接失敗 → 即プロキシへフォールバック」するため。
ただし**初回のバッチだけは直接呼び出しの15秒タイムアウトを待つぶん遅くなる**。
一度失敗すると `.gemini_direct_disabled_until` に記録され、以降は直接呼び出しをスキップして
プロキシ直行になる。**これは仕様どおりの挙動で、バグではない。**
実機で「最初だけ遅い」と報告されても慌てないこと。

### 5-6. 呼び出し側（L167-172）の置換後

```python
            # request_options={"timeout": 40} は共通モジュールに同等機能が無いため削除。
            # タイムアウトは gemini_client.py 側の固定値(直接15秒 / プロキシ60秒)になる。
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL_NAME,
                contents=prompt,
                config=_GeminiGenerateConfig(temperature=0.1, safety_settings=safety_settings),
            )
```

---

## 6. 【今回の固有事情】付随ファイルが1つも無い

`pdf_translator` には `requirements.txt` / `README.md` / `CHANGELOG.md` / `run_pdf_translator.bat` が
既にあったが、**`ppt_translation_20260309_03.py` は単独のファイルとして
`PythonScripts\excel\` 直下に置かれているだけ**で、付随ファイルが存在しない。
しかも今回は `PythonScripts\Powerpoint\ppt_translator\` という**新しい空フォルダへ移す**。

したがって、次の4つを**新規に作る**必要がある。着手前にユーザーへ確認すること（§11）。

### (1) `requirements.txt`（新規・必須）

```
# ppt_translation の依存ライブラリ
#
# Gemini API の呼び出しは共通モジュール gemini-common-tools の gemini_client.py
# 経由へ移行したため、旧SDK google-generativeai は 20260812_01 以降不要。
# gemini_client.py 自体は requests を使うため、別途インストールが必要。

python-pptx
requests      # gemini_client.py が使用
```

`requests` の追加は**必須**。起動用batが専用のvenvを作ってそこに
`pip install -r requirements.txt` する構成にする場合、**`requests` を書いておかないと venv 内に
入らず、`gemini_client` の import が失敗する**（＝ツールは起動するがAI呼び出し時にエラー）。

### (2) `run_ppt_translator.bat`（新規）

`pdf_translator/run_pdf_translator.bat` をひな形にする。**そのままコピーせず、次の2点を必ず直すこと。**

- ワイルドカードを `ppt_translation_????????_??.py` にする
  （**フォルダ名は `ppt_translator` だがファイル名の接頭辞は `ppt_translation`**。ここを間違えると
  「起動対象が見つからない」で止まる）
- 表示文字列の「PDF」を「PowerPoint」に直す

認証情報のチェックは、**`GEMINI_API_KEY` と `GEMINI_PROXY_URL` の両方が空のときだけ**警告する形にする:

```bat
if not "%GEMINI_API_KEY%"=="" goto :run_tool
if not "%GEMINI_PROXY_URL%"=="" goto :run_tool
goto :warn_no_credentials
```

**このファイルは絶対にASCIIのみで書くこと。** 日本語を入れるとShift-JIS誤読で
`goto` が壊れて起動しなくなる（`pdf_translator/CHANGELOG.md` の `[20260722_02]` に実際の被害が
記録されている）。`chcp 65001` では直らない。書き終えたら必ず
`python3 -c "print(sum(1 for b in open('run_ppt_translator.bat','rb').read() if b>127))"`
で 0 になることを確認する。

### (3) `README.md`（新規）

`pdf_translator/README.md` の構成をひな形にする。特に次は必ず書く:

- 必要な環境変数は `GEMINI_API_KEY` / `GEMINI_PROXY_URL` の**どちらか一方以上**であること
- `gemini_client.py` の置き場所（上位の `common` を自動探索。`GEMINI_COMMON_DIR` で明示指定可）
- モデルが固定になったこと、`GEMINI_MODEL` で上書きできること
- 「最初のバッチだけ遅い」のは仕様であること

### (4) `CHANGELOG.md`（新規）

`pdf_translator/CHANGELOG.md` の書式（`## [YYYYMMDD_NN] - YYYY-MM-DD` + 追加ファイル/更新ファイル）に
合わせる。初版なので、`[20260309_03]` までの履歴は元ファイルの docstring から起こして
1エントリにまとめておくと親切（元ファイル冒頭に変更内容が箇条書きで残っている）。

---

## 7. シム実装

**`pdf_translator/pdf_translator_20260812_01.py` の L215〜L408 をそのままコピーする。**
`ppt_translation` に必要な要素（`.parts` / `safetySettings` / 上位ディレクトリ探索）は
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

コピー後にコメント文中の「PDF」「pdf_translator」を「PowerPoint」「ppt_translator」へ直すこと
（動作には影響しないが、読む人が混乱する）。

### 探索パスについて（重要）

```
PythonScripts\
├── common\
│   └── gemini_client.py
└── Powerpoint\
    └── ppt_translator\
        └── ppt_translation_YYYYMMDD_NN.py     ← ここから見て common は「2つ上」
```

**1つ上（`Powerpoint\common`）では見つからない。** 上位を順に探す方式（1つ上・2つ上・3つ上）に
なっているので、コピーしたままで正しく解決する。移行元の `PythonScripts\excel\` に置いた場合も
「1つ上」で見つかるため、**どちらの場所に置いても動く**（移行期間中に両方で試せる）。

---

## 8. テスト方法（Windows / 実API 非依存で検証する）

偽の `gemini_client` を **対象モジュールのロード前に** `sys.modules` へ注入して payload を捕捉する。
`pdf_translator/tests/test_pdf_translator_20260812_01.py` がそのまま雛形になる（75項目）ので、
**新規に書き起こさずコピーして差分を当てるのが速い。**

### 検証環境について（本セッションで実測済み）

| ライブラリ | Linuxコンテナ | 対応 |
|---|---|---|
| `python-pptx` | **`pip install python-pptx` で入る。動作確認済み（1.0.2）** | 本物を使える |
| `requests` | 導入済み | そのまま |
| `tkinter` | **入らない**（apt必須） | `sys.modules` へスタブを注入する |

`python-pptx` が本物で動くのは大きい。**合成PPTXを実際に生成して、翻訳文の書き戻しまで
エンドツーエンドで検証できる**（AI呼び出しだけ偽物に差し替える）。

### 検証すべき項目

- payload形状 / `model` が明示的に渡るか / `temperature: 0.1` が `generationConfig` に camelCase で載るか
- **`safetySettings` が4カテゴリ分そのまま載るか**
- **`response.parts` が読めるか（空応答時に `[]` になり、`ValueError` → リトライになるか）**
- `response.text` が読めるか / payload が `json.dumps` 可能か
- 空・壊れたレスポンスで例外を投げないか
- 3回リトライ・3バッチ連続エラーのフェイルファストが従来どおり動くか
- 認証情報判定の4パターン（**プロキシURLのみ = 通る** が特に重要）
- 共通モジュール未配置時に「探索したパス」を含むエラーが出るか
- **`init_gemini()` がネットワークアクセスなしで完了するか**（`list_models` を消せている証拠）
  - `pdf_translator` のテストでは `socket.socket` を差し替えて「ソケット生成したら失敗」に
    してから `init_gemini()` を呼び、成功することで証明した。**同じ手が使える。**
- 共通モジュール探索が「2つ上が common」のレイアウトで正しく解決するか

### PPT固有のエンドツーエンド検証（ここが今回の肝）

合成PPTX（タイトル＋本文＋**表**＋**スピーカーノート**、runごとにフォントサイズ・太字・色を設定）を
生成し、翻訳を適用したあとで次を確認する:

- 翻訳文が run に書き戻されていること
- **run単位の書式（`font.size` / `font.bold` / `font.color.rgb` / 段落の配置）が翻訳前後で不変**であること
- 表のセル・スピーカーノートも翻訳対象として拾えていること
- 日本語指定時に `run.font.name` が `游ゴシック` になること（既存仕様）

**注意（`pdf_translator` で実際に踏んだ失敗）**: 「出力ファイルが完全一致するはず」と決め打ちで
アサーションを書くと外れる。PDFでは墨消しの塗り矩形が増えるため座標の集合が一致せず、テストが
落ちた（実装は正しかった）。PPTXも**zipのタイムスタンプが毎回変わるためバイト比較はできない**。
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
a = funcs('ppt_translation_20260309_03.py'); b = funcs('ppt_translation_20260812_01.py')
print("未変更:", sorted(k for k in a if k in b and a[k] == b[k]))
print("変更  :", sorted(k for k in a if k in b and a[k] != b[k]))
print("削除  :", sorted(k for k in a if k not in b))
print("新規  :", sorted(k for k in b if k not in a))
EOF
```

**PowerPoint処理側（`translate_ppt_document_thread` / `WordProgressWindow` / `select_file` /
`is_translatable` / `translate_super_fast_parallel` / `get_logger`）が「未変更」に並ぶことを確認する。**
変更されてよいのは **`check_dependencies` / `init_gemini` / `translate_batch_gemini` の3つだけ**
（`pdf_translator` でも全く同じ3つだった）。

さらに強い証拠として、`pdf_translator` では**旧版と新版に同じ翻訳文を与えて出力を比較し、完全一致を
確認した**。PPTでも同じことができる（run単位の書式とテキストを両方から抽出して比較する）。
これができると「AI呼び出し以外は何も変わっていない」を実物で示せるので、強く推奨する。

---

## 9. ハマりどころ（先行4ツールで実際に踏んだもの）

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
`ppt_translation` では L83-88（ガード本体）が対象。新規に作るbat・READMEにも同じ配慮が要る。

### (2) 【今回いちばん時間を無駄にしやすい】付随ファイルは着手前に全部そろえてもらう

`pdf_translator` のセッションでは `run_pdf_translator.bat` がアップロードされておらず、
仕様の説明文から**バッチを丸ごと再構成してしまった**。その直後に実物が届いたため、再構成は破棄して
実物へ最小パッチを当て直す羽目になった（作業の手戻り）。

**今回は付随ファイルが1つも無いことが分かっているので状況は違うが、逆に「実は
`PythonScripts\excel\` に起動用batや `requirements.txt` があった」という可能性は残る。
着手前に必ずユーザーへ確認すること**（§11）。

### (3) `gemini_client` の import は `try/except` にする

無条件 import にすると、共通モジュール未配置時に**ツール自体が起動できなくなる**。
`try/except` で受けて、実際にAI呼び出しが行われた時点で「探索したパス」「元のエラー」
「`GEMINI_COMMON_DIR` で指定できること」を含むエラーを出す。

ただし `ppt_translation` は**全機能がAI翻訳**なので、`check_dependencies()` / `init_gemini()` の
時点で分かりやすく案内して終了させてよい（`excel_translation` / `pdf_translator` でも同じ判断をした）。
「起動だけはできるが何もできない」より親切。

### (4) `model` は必ず明示的に渡す

`generate_advanced(payload, model=model)` の `model` を省略すると共通モジュール側の既定モデルに落ちる。
UI表示と実際のモデルが食い違う silent failure の原因になる。

### (5) 設計提案書・行番号を鵜呑みにしない

`excel_translation` では、事前の設計提案書が「`from google.genai import types` が L21 にある」と
書いていたが、**実物は旧SDK `google.generativeai` で、そんな行は存在しなかった**。

**必ず対象ファイルを自分で読み、grepで実数を数えてから着手すること。**
本資料の §5 の行番号も `_20260309_03` 時点のものなので、着手時に必ず現物で確認すること。

### (6) 移行と無関係な既存不具合を「移行のせい」と誤診しない

切り分け手順:

1. **AIが翻訳文を返しているか**を見る。返っていれば通信・レスポンス解析は成功しており、移行のコアは動いている。
2. 疑わしい関数が移行前後で同一かをハッシュで確認する（§8 の AST 比較スクリプト）。

`ppt_translation` に元からある挙動で、**移行スコープ外なので触らないもの**:

- `translate_super_fast_parallel()`（L254-259）… チャンクが例外で失われたとき `[""] * batch_size` で
  埋めるため、最終チャンクだと翻訳結果の件数が合わなくなりうる。
- `WordProgressWindow`（L263）… PowerPointのツールなのにクラス名が `Word` のまま
  （Word版から流用した名残）。動作に影響はない。
- 出力ファイル名（L327-328）… `target_language.split()[0].lower()` を使うため
  `_gemini_japanese.pptx` になる（`pdf_translator` の `_ja.pdf` のような2文字コードではない）。
  **統一したくなるが、既存の出力名が変わるとユーザーの運用に影響するので、依頼が無い限り変えない。**
- 素の `except:`（L274 / L313 / L320）… 移行とは無関係。

これらは**実機で報告されたときに「移行のせいではない」と即答できるよう**記録している。

---

## 10. 納品

- **このツール群はローカルではGitを使わない運用**。ユーザーはファイルをダウンロードして差し替える。
  そのため、**リポジトリへのpushとは別に、成果物ファイルを個別に送ること**。
  今回は新フォルダを作るので、**送るファイルは5つ**:
  `ppt_translation_20260812_01.py` / `requirements.txt` / `run_ppt_translator.bat` /
  `README.md` / `CHANGELOG.md`
- バージョン管理はファイル名の日付＋連番。**過去リビジョンは削除せず残す。**
- **実機検証できていないことは必ず明記する**。特に「プロキシ経由で実際に応答が返るところは未確認」は
  毎回書く（Linuxコンテナからは共通モジュールにもプロキシにも到達できないため）。
- 実機で確認してほしい項目を箇条書きで残す。`ppt_translation` なら最低限:
  1. 新フォルダ `PythonScripts\Powerpoint\ppt_translator\` に5ファイルを配置
  2. `GEMINI_API_KEY` / `GEMINI_PROXY_URL` 設定後、**コマンドプロンプトを開き直してから**起動
  3. **起動できること**（移行前は初期化で落ちていた点）
  4. 実際にPPTXを翻訳し、`translation_debug.log` と画面に `[gemini_client]` のログが出たうえで
     翻訳結果が返ること
  5. フォント・色・配置・表・スピーカーノートの書式が従来どおり保持されていること
     （PPT処理側は未変更なので影響しない想定）
  6. 初回バッチだけ遅くなる場合があるが仕様であること（§5-5）

---

## 11. 着手前にユーザーへ確認すること

1. **`PythonScripts\excel\` に、`ppt_translation` 用の起動バッチや `requirements.txt` が
   既にあるか。** あるなら実物をアップロードしてもらう（§9-(2) の手戻りを防ぐ）。
   無ければ新規に作る（§6）。
2. **起動用バッチを新規に作ってよいか。** `pdf_translator` と同じ「初回のみvenv作成＋
   `pip install`、最新ファイルを自動起動」方式でよいか。不要なら作らない。
3. **移行元 `PythonScripts\excel\ppt_translation_20260309_03.py` をどうするか。**
   新フォルダへ移した後、元の場所のファイルを残すか削除するかはユーザー判断。
   （リポジトリ上は旧版を必ず残す運用なので、リポジトリ側は残す。）

---

## 12. 未確定・要判断

- **「直接接続の復活お知らせ」機能を入れるか。**
  TYPE A（`outlook_total_organizer`）にのみ実装済み。3ツール以上に入れると同じ日に複数回
  ポップアップが出るため、集約方針が未決のまま `excel_translation` / `pdf_translator` では
  **見送った**。`ppt_translation` でも同様に見送るのが自然。
- `GEMINI_RETRY_DIRECT_AFTER_SECONDS` は 2026-08-12 にユーザー判断で 86400（1日）へ変更する運用に
  なった。この環境変数は `gemini_client.py` が読むため**全ツール共通に効く**。
  `ppt_translation` 側で個別に変えることはできない。
- 自動モデル検出を外したことで、将来モデル名が変わったときに**手で更新が必要**になる。
  環境変数 `GEMINI_MODEL` で上書きできるようにしてあるので実運用上は困らないはずだが、
  READMEに書いておくこと。
- **5ツール目の完了後**は、`gemini_client.py` を使うツールが5つになる。モデル名の一括変更や
  「復活お知らせ」の集約など、**共通モジュール側でまとめて面倒を見る設計**を検討する時期。
  必要になったら `gemini-common-tools` 側で議論すること（本ツールのスコープ外）。

---

## 13. ユーザーとのコミュニケーションについて

- **越智さんはGitの用語に不慣れ**。`git push` / PR / マージといった語をそのまま使わず、
  **必要なら例え話で補足する**。実際に「清書版のノート（main）と下書きノート（ブランチ）」
  「下書きを清書版に入れていいですかの申請書（PR）」という説明で通じた。
- PRの作成・マージは**明示的に依頼されてから**行う。勝手に作らない。
- 説明は結論から。日本語で。
