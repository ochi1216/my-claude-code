# 引継ぎ: pdf_translator の Gemini APIプロキシ対応（TYPE C）

2026-08-12 作成。`outlook_total_organizer`（TYPE A）と `excel_translation`（Git未管理からの新規追加）を
同じ方式へ移行した実作業から得た知見をまとめたもの。**「先に読むと事故を防げること」を優先して書いてある。**

対象: `C:\Users\nx023836\Documents\PythonScripts\PDF_translation\pdf_translator\pdf_translator_20260722_08.py`

**この資料の使い方**: 新しいClaude Codeセッションを開き、この資料と対象ファイル一式
（`pdf_translator_20260722_08.py` / `requirements.txt` / `run_pdf_translator.bat` /
`CHANGELOG.md` / `README.md`）をアップロードして作業を依頼する。
この資料は `my-claude-code` リポジトリのルートにも置いてあるため、セッションからはリポジトリを
読むだけでも参照できる。

---

## 0. 結論から: このツール特有の「効く」ポイント

先行2ツールと違い、**pdf_translator は移行しないと起動すらできない**。理由と対応は §5 に詳述するが、
先に頭出しすると次の5点。ここを外すと必ず作業が空回りする。

| # | 箇所 | 何が起きるか |
|---|---|---|
| 1 | `genai.list_models()`（L245） | **起動時にネットワークを叩くため、遮断下では初期化に失敗して `sys.exit(1)`。ツールが立ち上がらない** |
| 2 | `response.parts`（L327） | シムが `.parts` を持たないと `AttributeError` → 全バッチが3回リトライ後に失敗 |
| 3 | `safety_settings`（L322） | payloadへ載せないと `BLOCK_NONE` 指定が消え、内容によっては応答が空になる |
| 4 | `request_options={"timeout": 40}`（L323） | 共通モジュールに同等機能なし。削除して挙動差を記録する |
| 5 | `run_pdf_translator.bat` / `requirements.txt` | `GEMINI_API_KEY` 前提の警告と旧SDK依存が残り、プロキシ専用構成で毎回警告が出る |

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

今回の対象: **pdf_translator**（TYPE C = Claude Codeでの作業歴なし・Git未管理）

### TYPE C は何が違うのか

コードの移行作業そのものは TYPE A / excel_translation と同じ。違うのは **Git側の段取りだけ**。

- リポジトリ `ochi1216/my-claude-code` に `pdf_translator/` フォルダがまだ存在しない
- したがって「**現状のファイルをそのまま先にコミットして基準を作る**」工程が最初に必要（§4）
- これを飛ばすと、旧版との `diff` が取れず「移行で何が変わったか」を客観的に示せなくなる

---

## 2. 参照資料（推測で書かず、必ず実物を読むこと）

- 全体設計: `gemini-common-tools` リポジトリの `GEMINI_MIGRATION_HANDOVER.md`
- 共通モジュール本体: 同リポジトリの `gemini_client.py`
  公開リポジトリなので匿名cloneで取得できる:
  `git clone --depth 1 https://github.com/ochi1216/gemini-common-tools`
  **payloadの送られ方（`_call_direct_advanced` / `_call_proxy_advanced`）を必ず自分の目で確認すること。**
  「プロキシは payload をそのまま透過し、`model` だけ `_gemini_model` フィールドに載せ替える」という
  事実を知らないと、`safetySettings` を載せてよいか判断できない。
- 移行実装の実例（新しい順に読むと早い）:
  - `my-claude-code` の `excel_translation/excel_translation_20260812_01.py` の冒頭
    … **旧SDK（`google.generativeai`）からの移行例。pdf_translator と同じ系統なのでこれが一番近い**
  - `my-claude-code` の `excel_translation/CHANGELOG.md`（記載フォーマットの見本）
  - `outlook_total_organizer/outlook_total_organizer_20260812_02.py`（TYPE A。新SDK `google.genai` からの移行例）
- 前回の引継ぎ資料: `HANDOVER_onenote_gemini_proxy.md`（本資料はこれの改訂版。重複は最小限にしてある）

---

## 3. 移行の全体方針: 「互換シム」1つで置き換える

`genai` SDK の呼び出しを個別に全部書き換えてはいけない。`genai.Client` と同じインターフェースだけを
持つ薄い互換シムを1つ作り、**クライアント生成箇所だけ**を差し替える。

これにより、レスポンスを読む側（`response.text` を正規表現で解析して番号付きリストへ戻す処理）や、
リトライ・フェイルファスト・進捗表示のロジックは**一切変更しないで済む**。

**4ツールすべてでシムの形を揃えること。** 呼び出しの形は
`client.models.generate_content(model=..., contents=..., config=...)` に統一する。
pdf_translator は旧SDKの `GenerativeModel.generate_content(prompt, ...)` 形式なので、
その場に合わせた別形のシムを作ることもできるが、**揃えたほうが後の保守が楽なので統一を推奨**する
（excel_translation でも同じ判断をした）。

---

## 4. Git環境の作り方（TYPE C 固有。ここを最初にやる）

リポジトリ: `ochi1216/my-claude-code`（セッション開始時にクローン済みのはず）

```bash
# 1. 指定された作業ブランチを作る（ブランチ名はセッション開始時に指示される）
git fetch origin main
git checkout -B claude/<指示されたブランチ名> origin/main

# 2. フォルダを作り、アップロードされた「現状のファイル」をそのまま置く
mkdir -p pdf_translator/tests
#   pdf_translator_20260722_08.py / requirements.txt / run_pdf_translator.bat
#   CHANGELOG.md / README.md をコピー

# 3. ★重要★ ここで一度コミットする（＝移行前の基準点を作る）
git add pdf_translator && git commit -m "Add pdf_translator as-is (baseline before Gemini proxy migration)"
```

**手順3を必ず先に単独でコミットすること。** これをやっておくと、次のコミットの `diff` が
「移行で変えた箇所」だけになり、CHANGELOGに書く「変更関数」「未変更であることの証明」を
客観的に示せる。excel_translation ではこれで「Excel処理側の17定義が旧版と完全一致」を証明できた。

そのうえで:

- 新ファイルは **`pdf_translator_<作業日>_01.py`**（例: 8月13日なら `pdf_translator_20260813_01.py`）。
  **日付は必ず作業当日を確認して決める**（`date` コマンド等）。`v` 記号は付けない。同日再リリースは `_02`。
- **旧版 `pdf_translator_20260722_08.py` は削除しない。** 併存させる（リポジトリの運用ルール）。
- 旧リビジョン（`_01`〜`_07`）が手元にあるなら一緒にアップロードしてもよいが必須ではない。
  **少なくとも直前版 `_08` は必ずアップロードすること**（差分検証の基準になるため）。
- ルートの `README.md` にツール一覧の項目を1つ追記する（既存の書式に合わせる）。
- 最後に `git push -u origin <ブランチ名>`。PR作成とマージは**ユーザーから明示的に依頼されてから**行う。

---

## 5. pdf_translator の事前分析（本セッションで実施済み。ここが本題）

`pdf_translator_20260722_08.py` を通読して洗い出した移行対象。**行番号は `_20260722_08` 時点のもの。**

### 5-1. 移行対象マップ

| 行 | 内容 | 対応 |
|---|---|---|
| L179 | `import google.generativeai as genai` | 削除 |
| L180-182 | `HAS_GEMINI` | 共通モジュールを読めたかどうかへ意味を変更 |
| L194-197 | `check_dependencies()` の `google-generativeai` | 共通モジュールのチェックへ差し替え |
| L212 | `gemini_model = None`（グローバル） | シムのクライアントを入れる（名前は `gemini_client` を推奨） |
| L233-238 | `GEMINI_API_KEY` 必須ガード | `gemini_credentials_available()` へ |
| L241 | `genai.configure(api_key=api_key)` | 削除 |
| **L244-264** | **`genai.list_models()` による自動モデル検出** | **削除。固定モデル名へ（最重要・§5-2）** |
| L290 | `if not gemini_model` | シムのクライアント判定へ |
| L307-312 | `safety_settings`（BLOCK_NONE ×4） | **payload の `safetySettings` へ載せる（§5-4）** |
| L319-324 | `gemini_model.generate_content(...)` | シム経由へ置換 |
| L321 | `genai.types.GenerationConfig(temperature=0.1)` | ローカルの config クラスへ |
| L323 | `request_options={"timeout": 40}` | **削除（同等機能なし・§5-5）** |
| **L327** | **`if not response.parts:`** | **シムに `.parts` を持たせる（§5-3）** |
| L331 | `response.text.strip()` | 変更不要（シム対応済み） |

Grounding（`google_search` / `tools=`）は**未使用**、`response_schema` も**未使用**、
`system_instruction` も**未使用**（プロンプト本文に指示を書き込む方式）。よってシムの拡張は
`safetySettings` と `.parts` の2点だけで足りる。

### 5-2. 【最重要】`genai.list_models()` で起動できなくなる

```python
# L240-264（現状）
genai.configure(api_key=api_key)
available_models = []
for m in genai.list_models():                    # ← ネットワークアクセス
    if 'generateContent' in m.supported_generation_methods:
        available_models.append(m.name)
...
gemini_model = genai.GenerativeModel(target_model_name)
```

`init_gemini()` は `__main__` から呼ばれ、`False` を返すと `sys.exit(1)`（L1232-1233）。
**遮断下では `list_models()` が例外を投げ、`except` に落ちて「API初期化エラー」ダイアログ →
即終了する。** つまりこのツールは移行しない限り起動すらできない。これが先行2ツールとの最大の違い。

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
ただし `gemini-2.5-flash` は他3ツールで実績があり、実害はまず無い。CHANGELOGに明記すること。

### 5-3. 【要注意】`response.parts` を見ている

```python
# L327-329
if not response.parts:
    if logger: logger.warning(...)
    raise ValueError("Empty response from API")
```

TYPE A / excel_translation のシムは `.text` と `.usage_metadata` しか持たない。
このままだと `AttributeError` になり、`except` に拾われて**毎バッチ3回リトライ→全滅→
3バッチ連続エラーでフェイルファスト**という、原因の見えない止まり方をする。

シムに `.parts` を持たせて解決する。空応答のとき `[]` を返せば、**元の
「空ならValueErrorでリトライ」という挙動がそのまま保たれる**（ここが大事）。

### 5-4. `safety_settings` を payload へ載せる

L307-312 の `safety_settings` は既にREST形式の dict のリスト（`category` / `threshold`）なので、
**そのまま `payload["safetySettings"]` に入れればよい**。載せ忘れると `BLOCK_NONE` 指定が消え、
資料の内容によっては応答が空になり「一部バッチだけ翻訳されない」という切り分けにくい症状になる。

### 5-5. `request_options={"timeout": 40}` は等価な置き換えができない

共通モジュールのタイムアウトは `gemini_client.py` 側の固定値（**直接15秒 / プロキシ60秒**）で、
呼び出し側から指定する口が無い。**引数は削除し、CHANGELOGに挙動差として明記する。**

実害は小さい。理由: このツールは3回リトライ（3秒間隔）を自前で持っており、
`gemini_client` 側も「直接失敗 → 即プロキシへフォールバック」するため。
ただし**初回のバッチだけは直接呼び出しの15秒タイムアウトを待つぶん遅くなる**。
一度失敗すると `.gemini_direct_disabled_until` に記録され、以降は直接呼び出しをスキップして
プロキシ直行になる（既定30分、環境変数 `GEMINI_RETRY_DIRECT_AFTER_SECONDS` で変更可）。
**これは仕様どおりの挙動で、バグではない。** 実機で「最初だけ遅い」と報告されても慌てないこと。

### 5-6. 付随ファイルの修正（コードだけ直して満足しないこと）

**`requirements.txt`**

```
google-generativeai>=0.5   ← 削除
PyMuPDF>=1.23              ← 残す
requests                   ← 追加（gemini_client.py が使う）
```

`requests` の追加は**必須**。`run_pdf_translator.bat` は専用の venv を作ってそこに
`pip install -r requirements.txt` するため、**`requests` を書いておかないと venv 内に入らず、
`gemini_client` の import が失敗する**（＝ツールは起動するがAI呼び出し時にエラー）。

**`run_pdf_translator.bat`**（L47・L77-85）

```bat
if "%GEMINI_API_KEY%"=="" goto :warn_no_api_key
```

プロキシ専用構成では `GEMINI_API_KEY` が空でも正常なので、**このままだと毎回警告＋`pause` で
止まる**（前回引継ぎ資料 4-(2) と同じ問題のバッチ版）。両方空のときだけ警告するよう変更する。

```bat
if not "%GEMINI_API_KEY%"=="" goto :run_tool
if not "%GEMINI_PROXY_URL%"=="" goto :run_tool
goto :warn_no_credentials
```

**このファイルは絶対にASCIIのみで書くこと。** 日本語を入れるとShift-JIS誤読で
`goto` が壊れて起動しなくなる（`CHANGELOG.md` の `[20260722_02]` に実際の被害が記録されている）。
`chcp 65001` では直らない。既存ファイルの先頭コメントにも同じ警告がある。

なお、このバッチは `pdf_translator_????????_??.py` を名前降順で拾って最新版を起動するので、
**新ファイルを置くだけで自動的に切り替わる**（`pdf_translator_20260813_01.py` は `_20260722_08` より新しいと判定される）。バッチ側にファイル名を書く必要はない。

---

## 6. ハマりどころ（先行3ツールで実際に踏んだもの）

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
pdf_translator では L233-238（ガード本体）と、バッチファイル・READMEの記述が対象。

### (2) 共通モジュールの探索パスは `../common` 固定にしてはいけない

TYPE A のシムは `../common`（1つ上）固定だった。しかし会社PCの実際の配置は:

```
PythonScripts\
├── common\
│   └── gemini_client.py
└── PDF_translation\
    └── pdf_translator\
        └── pdf_translator_YYYYMMDD_NN.py     ← ここから見て common は「2つ上」
```

**1つ上（`PDF_translation\common`）では見つからない。** excel_translation でも同じ構成で、
上位ディレクトリを順に探す方式にして解決した（3レイアウトで動作確認済み）。§7 のコードをそのまま使う。

### (3) `gemini_client` の import は `try/except` にする

無条件 import にすると、共通モジュール未配置時に**ツール自体が起動できなくなる**。
`try/except` で受けて、実際にAI呼び出しが行われた時点で「探索したパス」「元のエラー」
「`GEMINI_COMMON_DIR` で指定できること」を含むエラーを出す。

ただし pdf_translator は**全機能がAI翻訳**なので、`check_dependencies()` / `init_gemini()` の
時点で分かりやすく案内して終了させてよい（excel_translation でも同じ判断をした）。
「起動だけはできるが何もできない」より親切。

### (4) `model` は必ず明示的に渡す

`generate_advanced(payload, model=model)` の `model` を省略すると共通モジュール側の既定モデルに落ちる。
UI表示と実際のモデルが食い違う silent failure の原因になる。

### (5) 設計提案書・行番号を鵜呑みにしない

excel_translation では、事前の設計提案書が「`from google.genai import types` が L21 にある」と
書いていたが、**実物は旧SDK `google.generativeai` で、そんな行は存在しなかった**。
提案どおりに `google.genai` を import していたら、未導入の会社PCで起動不能になっていた。

**必ず対象ファイルを自分で読み、grepで実数を数えてから着手すること。**
本資料の §5 の行番号も `_20260722_08` 時点のものなので、着手時に必ず現物で確認すること。

### (6) 移行と無関係な既存不具合を「移行のせい」と誤診しない

`outlook_total_organizer` では移行直後の不具合が**実は既存バグ**だった。切り分け手順:

1. **AIが翻訳文を返しているか**を見る。返っていれば通信・レスポンス解析は成功しており、移行のコアは動いている。
2. 疑わしい関数が移行前後で同一かをハッシュで確認する（§8 の AST 比較スクリプトが便利）。

参考までに、pdf_translator の `translate_super_fast_parallel()` には
「チャンクが例外で失われたとき `[""] * batch_size` で埋めるため、最終チャンクだと
翻訳結果の件数が合わなくなりうる」という**既存の挙動**がある（L407-412）。
**移行スコープ外なので触らないこと。** ただし実機で件数ズレが報告されたときに
「移行のせいではない」と即答できるよう、ここに記録しておく。

---

## 7. シム実装（pdf_translator 版・そのまま使える完成形）

`excel_translation_20260812_01.py` のシムに `.parts` と `safetySettings` を足したもの。
`import sys` / `import os` は既にあるので追加不要。

```python
# ============================================================
# Gemini 共通クライアント(gemini_client.py)への互換シム
# ============================================================
_GEMINI_COMMON_DIR_ENV = os.environ.get("GEMINI_COMMON_DIR")
if _GEMINI_COMMON_DIR_ENV:
    _COMMON_DIR_CANDIDATES = [_GEMINI_COMMON_DIR_ENV]
else:
    # 会社PCでは本スクリプトが PythonScripts\PDF_translation\pdf_translator\ に、
    # gemini_client.py が PythonScripts\common\ に置かれるため、正解は「2つ上」。
    # 他ツール(1つ上が common)の配置でも動くよう、上位を順に探す。
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    _COMMON_DIR_CANDIDATES = [
        os.path.abspath(os.path.join(_SCRIPT_DIR, *([os.pardir] * _n + ["common"])))
        for _n in (1, 2, 3)
    ]

_COMMON_DIR = next(
    (_d for _d in _COMMON_DIR_CANDIDATES
     if os.path.isfile(os.path.join(_d, "gemini_client.py"))),
    _COMMON_DIR_CANDIDATES[0])

if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

try:
    from gemini_client import generate_advanced as _generate_advanced
    _GEMINI_CLIENT_IMPORT_ERROR = None
except Exception as _e:
    _generate_advanced = None
    _GEMINI_CLIENT_IMPORT_ERROR = _e

HAS_GEMINI = _generate_advanced is not None

GEMINI_MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def _gemini_common_module_error_message():
    return ("Gemini共通モジュール(gemini_client.py)を読み込めませんでした。\n"
            f"探索したパス: {' / '.join(_COMMON_DIR_CANDIDATES)}\n"
            f"元のエラー: {_GEMINI_CLIENT_IMPORT_ERROR}\n\n"
            "gemini-common-tools を配置し、必要なら環境変数 GEMINI_COMMON_DIR で\n"
            "gemini_client.py のあるフォルダを指定してください。")


def _schema_to_jsonable(value):
    """REST APIのpayloadへ載せられる素のdict/listへ変換する保険。
    素のdict/listならそのまま返る。"""
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        return value
    for attr, kwargs in (("model_dump", {"mode": "json", "exclude_none": True, "by_alias": True}),
                         ("dict", {"exclude_none": True, "by_alias": True})):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return fn(**kwargs)
            except Exception:
                try:
                    return fn()
                except Exception:
                    pass
    return value


class _GeminiGenerateConfig:
    """genai.types.GenerationConfig 相当の設定オブジェクト。
    旧SDKへの依存を断つため、同等の入れ物をここに置く
    (シム側は getattr で読むだけなので実装差の影響を受けない)。"""
    def __init__(self, temperature=None, safety_settings=None,
                 system_instruction=None, response_mime_type=None, response_schema=None):
        self.temperature = temperature
        self.safety_settings = safety_settings
        self.system_instruction = system_instruction
        self.response_mime_type = response_mime_type
        self.response_schema = response_schema


class _CommonUsageMetadata:
    def __init__(self, usage):
        usage = usage if isinstance(usage, dict) else {}
        self.prompt_token_count = usage.get("promptTokenCount", 0)
        self.candidates_token_count = usage.get("candidatesTokenCount", 0)


class _CommonGeminiResponse:
    """generate_content(...) の戻り値互換。
    本ツールは response.parts で空応答を判定してから response.text を読むため、
    parts も提供する(空応答なら空リスト → 呼び出し側の
    「空ならValueErrorでリトライ」という既存の挙動がそのまま保たれる)。"""
    def __init__(self, raw):
        try:
            self.text = raw["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            self.text = ""
        try:
            self.parts = raw["candidates"][0]["content"]["parts"] or []
        except (KeyError, IndexError, TypeError):
            self.parts = []
        self.usage_metadata = _CommonUsageMetadata(
            raw.get("usageMetadata", {}) if isinstance(raw, dict) else {})


class _CommonGeminiModels:
    def generate_content(self, model=None, contents=None, config=None):
        if _generate_advanced is None:
            raise RuntimeError(_gemini_common_module_error_message())

        payload = {"contents": [{"parts": [{"text": contents}]}]}
        if config is not None:
            # safety_settings は既にREST形式(category/threshold)のdictリストなので
            # そのまま載せる。載せ忘れるとBLOCK_NONE指定が消え、応答が空になりうる。
            safety = getattr(config, "safety_settings", None)
            if safety:
                payload["safetySettings"] = _schema_to_jsonable(safety)

            system_instruction = getattr(config, "system_instruction", None)
            if isinstance(system_instruction, str) and system_instruction:
                payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
            elif isinstance(system_instruction, dict):
                payload["systemInstruction"] = system_instruction

            gen_cfg = {}
            mime = getattr(config, "response_mime_type", None)
            if mime:
                gen_cfg["responseMimeType"] = mime
            schema = getattr(config, "response_schema", None)
            if schema is not None:
                gen_cfg["responseSchema"] = _schema_to_jsonable(schema)
            temp = getattr(config, "temperature", None)
            if temp is not None:
                gen_cfg["temperature"] = temp
            if gen_cfg:
                payload["generationConfig"] = gen_cfg

        # model は明示的に渡す(共通モジュールの既定モデルへ勝手に落ちるのを防ぐ)
        raw = _generate_advanced(payload, model=model)
        return _CommonGeminiResponse(raw)


class _CommonGeminiClient:
    """api_key は gemini_client.py 側が環境変数から読むため、受け取るだけで使用しない。"""
    def __init__(self, api_key=None):
        self.models = _CommonGeminiModels()


def gemini_credentials_available():
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_PROXY_URL"))
```

呼び出し側（L319-324）の置換後:

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

## 8. テスト方法（Windows / 実API 非依存で検証する）

偽の `gemini_client` を **対象モジュールのロード前に** `sys.modules` へ注入して payload を捕捉する。
`excel_translation/tests/test_excel_translation_20260812_01.py` がそのまま雛形になる（40項目）ので、
**新規に書き起こさずコピーして差分を当てるのが速い。**

### 検証環境について（実測済み）

| ライブラリ | Linuxコンテナ | 対応 |
|---|---|---|
| `PyMuPDF` (`fitz`) | **`pip install PyMuPDF` で入る。動作確認済み** | 本物を使える |
| `requests` | 導入済み | そのまま |
| `tkinter` | **入らない**（apt必須） | `sys.modules` へスタブを注入する |

`fitz` が本物で動くのは大きい。**合成PDFを実際に生成して、翻訳文の書き戻しまで
エンドツーエンドで検証できる**（AI呼び出しだけ偽物に差し替える）。
既存 `CHANGELOG.md` にも「合成テスト用PDF（表＋チャート＋自由段落）」で検証した記録があるので、
同じ手法を再現できる。**最低限、罫線の座標が翻訳前後で完全一致することは確認しておくとよい**
（表・グラフを壊していないことの客観的な証拠になる）。

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
- 共通モジュール探索が「2つ上が common」のレイアウトで正しく解決するか

### 変更範囲を客観的に示す（CHANGELOGの裏付けになる）

```bash
python3 - <<'EOF'
import ast, hashlib
def funcs(p):
    src = open(p, encoding='utf-8').read(); lines = src.splitlines()
    return {n.name: hashlib.md5("\n".join(lines[n.lineno-1:n.end_lineno]).encode()).hexdigest()[:8]
            for n in ast.walk(ast.parse(src))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
a = funcs('pdf_translator_20260722_08.py'); b = funcs('pdf_translator_<新版>.py')
print("未変更:", sorted(k for k in a if k in b and a[k] == b[k]))
print("変更  :", sorted(k for k in a if k in b and a[k] != b[k]))
print("削除  :", sorted(k for k in a if k not in b))
print("新規  :", sorted(k for k in b if k not in a))
EOF
```

**PDFレイアウト処理側（`_analyze_page_graphics` / `extract_translatable_blocks` /
`apply_translations_to_pdf` / `_expand_box_safely` / `sample_background_color` など）が
「未変更」に並ぶことを確認する。** v02〜v08で積み上げた繊細な調整の塊なので、
ここに手を入れていないと示せることが安心材料になる。

---

## 9. 納品

- **このツール群はローカルではGitを使わない運用**。ユーザーはファイルをダウンロードして差し替える。
  そのため、**リポジトリへのpushとは別に、成果物ファイルを個別に送ること**。
- バージョン管理はファイル名の日付＋連番。**過去リビジョンは削除せず残す。**
- `CHANGELOG.md` は既存フォーマット（`## [YYYYMMDD_NN] - YYYY-MM-DD` + 追加ファイル/更新ファイル）に
  **合わせること**。`excel_translation/CHANGELOG.md` とは書式が違うので、pdf_translator 側の既存書式を優先する。
- **実機検証できていないことは必ず明記する**。特に「プロキシ経由で実際に応答が返るところは未確認」は
  毎回書く（Linuxコンテナからは共通モジュールにもプロキシにも到達できないため）。
- 実機で確認してほしい項目を箇条書きで残す。pdf_translator なら最低限:
  1. `GEMINI_API_KEY` / `GEMINI_PROXY_URL` 設定後、**コマンドプロンプトを開き直して**から `run_pdf_translator.bat` を実行
  2. **起動できること**（移行前は初期化で落ちていた点）
  3. 実際にPDFを翻訳し、`translation_debug.log` と画面に `[gemini_client]` のログが出たうえで翻訳結果が返ること
  4. 表・グラフ・棒グラフの色と罫線が従来どおり保持されていること（PDF処理側は未変更なので影響しない想定）
  5. 初回バッチだけ遅くなる場合があるが仕様であること（§5-5）

---

## 10. ユーザーとのコミュニケーションについて

- **越智さんはGitの用語に不慣れ**（前セッションで「ブランチとは」「PRとは」を質問された）。
  `git push` / PR / マージといった語をそのまま使わず、**必要なら例え話で補足する**。
  実際に「清書版のノート（main）と下書きノート（ブランチ）」「下書きを清書版に入れていいですかの申請書（PR）」
  という説明で通じた。
- PRの作成・マージは**明示的に依頼されてから**行う。勝手に作らない。
- 説明は結論から。日本語で。

---

## 11. 未確定・要判断

- **「直接接続の復活お知らせ」機能を pdf_translator にも入れるか。**
  TYPE A（`outlook_total_organizer`）にのみ実装済み。3ツール以上に入れると同じ日に複数回
  ポップアップが出るため、集約方針が未決のまま `excel_translation` では**見送った**。
  pdf_translator でも同様に見送るのが自然（揃えるなら通知状態ファイルを共通の場所に置く設計が必要）。
- `GEMINI_RETRY_DIRECT_AFTER_SECONDS` は 2026-08-12 にユーザー判断で 86400（1日）へ変更する運用になった。
  この環境変数は `gemini_client.py` が読むため**全ツール共通に効く**。pdf_translator 側で個別に変えることはできない。
- 自動モデル検出を外したことで、将来モデル名が変わったときに**手で更新が必要**になる。
  環境変数 `GEMINI_MODEL` で上書きできるようにしてあるので実運用上は困らないはずだが、
  READMEに書いておくこと。
