"""excel_translation_20260911_02.py の図形(Shape)保持・翻訳機能の検証テスト。

openpyxlはAutoShape(xdr:sp)・コネクタ(xdr:cxnSp)を読み書きできず、
load_workbook -> save の過程でこれらを丸ごと消してしまう(openpyxl自身が
「Shapes and drawings will be lost.」と明記している既知の制限)。本バージョンは
openpyxlの保存後にxlsx(ZIP)内の図形用XMLを直接操作して復元・翻訳する
(restore_and_translate_shapes)。本ファイルはその検証に特化する
(プロキシ移行・セル翻訳・中国語略号の検証は既存の
test_excel_translation_20260817_01.py / _20260812_01.py を参照)。

Windows / Excel / 実際のGemini APIに依存せず検証するため、偽の`gemini_client`を
対象モジュールのロード前にsys.modulesへ注入する。tkinter/pandasはスタブ化する。
openpyxlは実際に使用する(このコンテナに導入済み)。

LibreOffice(soffice)が使える環境では、実際にレンダリングして図形が消えず・
翻訳文が描画されることまで確認する(無ければそのテストのみスキップする)。

実行方法:
    python3 tests/test_excel_translation_20260911_02.py
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import types as pytypes
import zipfile

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "excel_translation_20260911_02.py")
WORKDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shape_test_tmp")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f"  ({detail})" if detail else ""))


# ------------------------------------------------------------
# GUI依存のスタブ(openpyxl・pandasは実物を使う)
# ------------------------------------------------------------
def _install_env_stubs():
    class _Any:
        def __init__(self, *a, **k): pass
        def __call__(self, *a, **k): return _Any()
        def __getattr__(self, _n): return _Any()

    tk = pytypes.ModuleType("tkinter")
    for attr in ("Tk", "Toplevel", "Frame", "Label", "Button", "Entry", "Listbox",
                 "Checkbutton", "OptionMenu", "LabelFrame", "StringVar",
                 "BooleanVar", "MULTIPLE", "END", "LEFT"):
        setattr(tk, attr, _Any())
    tk.font = pytypes.ModuleType("tkinter.font")

    filedialog = pytypes.ModuleType("tkinter.filedialog")
    filedialog.askopenfilename = lambda *a, **k: ""

    messagebox = pytypes.ModuleType("tkinter.messagebox")
    messagebox.CALLS = []

    def _record(kind):
        def _fn(title="", message="", *a, **k):
            messagebox.CALLS.append((kind, title, message))
            return True
        return _fn

    messagebox.showerror = _record("error")
    messagebox.showwarning = _record("warning")
    messagebox.showinfo = _record("info")
    messagebox.askwarning = _record("askwarning")

    tk.filedialog = filedialog
    tk.messagebox = messagebox
    sys.modules["tkinter"] = tk
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.messagebox"] = messagebox
    sys.modules["tkinter.font"] = tk.font

    # pandas は .xls(レガシー形式)読み込み専用で、本テストでは経路を通らない。
    # このコンテナには未導入のため最小限のスタブで足りる。
    pd = pytypes.ModuleType("pandas")
    pd.isna = lambda v: v is None
    pd.notna = lambda v: v is not None
    sys.modules.setdefault("pandas", pd)
    return messagebox


MESSAGEBOX = _install_env_stubs()


# ------------------------------------------------------------
# 偽 gemini_client (行ごとに YAKU: を前置して「翻訳」する)
# ------------------------------------------------------------
CAPTURED = {"calls": []}
_FAKE_MARKER_RE = re.compile(r'^<<<ITEM (\d+)>>>$')


def _fake_generate_advanced(payload, model=None, **kwargs):
    CAPTURED["calls"].append({"payload": payload, "model": model})
    prompt_text = payload["contents"][0]["parts"][0]["text"]
    lines = prompt_text.splitlines()
    start = next((i for i, l in enumerate(lines) if _FAKE_MARKER_RE.match(l.strip())), None)
    out_lines = []
    if start is not None:
        for line in lines[start:]:
            if _FAKE_MARKER_RE.match(line.strip()):
                out_lines.append(line.strip())
            elif line.strip():
                out_lines.append(f"YAKU:{line}")
            else:
                out_lines.append(line)
    text = "\n".join(out_lines)
    return {"candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}}


fake_gc = pytypes.ModuleType("gemini_client")
fake_gc.generate_advanced = _fake_generate_advanced
sys.modules["gemini_client"] = fake_gc

spec = importlib.util.spec_from_file_location("target_shapes", TARGET)
mod = importlib.util.module_from_spec(spec)
sys.modules["target_shapes"] = mod
spec.loader.exec_module(mod)

check("HAS_GEMINI が True", mod.HAS_GEMINI is True)


# ============================================================
# 合成xlsxの構築(3パターン: 単一ラン / 複数ラン混在書式 / 複数段落)
# ============================================================
def _build_test_xlsx(path):
    CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>
</Types>'''
    ROOT_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
    WORKBOOK = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Flow Chart" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
    WORKBOOK_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''
    STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="1"><fill><patternFill patternType="none"/></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>'''
    SHEET1 = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<dimension ref="A1"/>
<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Before PCA</t></is></c></row></sheetData>
<drawing r:id="rId1"/>
</worksheet>'''
    SHEET1_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>
</Relationships>'''
    # 図形1: 単一ラン(通常ケース) / 図形2: 複数ラン混在書式+複数段落(実データで頻出するケース)
    # / 図形3: 短い記号のみ(is_translatable=Falseで翻訳対象外になることを確認)
    DRAWING1 = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<xdr:twoCellAnchor>
<xdr:from><xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
<xdr:to><xdr:col>4</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>6</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
<xdr:sp macro="" textlink=""><xdr:nvSpPr><xdr:cNvPr id="2" name="Rectangle 1"/><xdr:cNvSpPr/></xdr:nvSpPr>
<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="2743200" cy="1524000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="4472C4"/></a:solidFill></xdr:spPr>
<xdr:txBody><a:bodyPr/><a:p><a:r><a:rPr lang="en-US" sz="1800" b="1"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:rPr><a:t>Generate manhours and cost.</a:t></a:r></a:p></xdr:txBody>
</xdr:sp><xdr:clientData/>
</xdr:twoCellAnchor>
<xdr:twoCellAnchor>
<xdr:from><xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>7</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
<xdr:to><xdr:col>4</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>12</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
<xdr:sp macro="" textlink=""><xdr:nvSpPr><xdr:cNvPr id="3" name="Rectangle 2"/><xdr:cNvSpPr/></xdr:nvSpPr>
<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="2743200" cy="1524000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="C00000"/></a:solidFill></xdr:spPr>
<xdr:txBody><a:bodyPr/>
<a:p><a:r><a:rPr lang="en-US" sz="1400"/><a:t>Generate the </a:t></a:r><a:r><a:rPr lang="en-US" sz="1400" b="1"><a:solidFill><a:srgbClr val="FFFF00"/></a:solidFill></a:rPr><a:t>Manufacturing Plan</a:t></a:r><a:r><a:rPr lang="en-US" sz="1400"/><a:t>. Use the Template.</a:t></a:r></a:p>
<a:p><a:r><a:rPr lang="en-US" sz="1400"/><a:t>Second line here</a:t></a:r></a:p>
</xdr:txBody>
</xdr:sp><xdr:clientData/>
</xdr:twoCellAnchor>
<xdr:twoCellAnchor>
<xdr:from><xdr:col>5</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
<xdr:to><xdr:col>6</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>2</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
<xdr:sp macro="" textlink=""><xdr:nvSpPr><xdr:cNvPr id="4" name="Symbol"/><xdr:cNvSpPr/></xdr:nvSpPr>
<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="300000" cy="300000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr>
<xdr:txBody><a:bodyPr/><a:p><a:r><a:rPr lang="en-US" sz="1000"/><a:t>-</a:t></a:r></a:p></xdr:txBody>
</xdr:sp><xdr:clientData/>
</xdr:twoCellAnchor>
</xdr:wsDr>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("xl/workbook.xml", WORKBOOK)
        z.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        z.writestr("xl/styles.xml", STYLES)
        z.writestr("xl/worksheets/sheet1.xml", SHEET1)
        z.writestr("xl/worksheets/_rels/sheet1.xml.rels", SHEET1_RELS)
        z.writestr("xl/drawings/drawing1.xml", DRAWING1)


shutil.rmtree(WORKDIR, ignore_errors=True)
os.makedirs(WORKDIR, exist_ok=True)
ORIGINAL = os.path.join(WORKDIR, "shape_test.xlsx")
OUTPUT = os.path.join(WORKDIR, "shape_test_out.xlsx")
_build_test_xlsx(ORIGINAL)


# ============================================================
# 単体検証: 抽出・判定
# ============================================================
import openpyxl  # noqa: E402  (スタブ化していないので実物を使う)
import xml.etree.ElementTree as ET  # noqa: E402

with zipfile.ZipFile(ORIGINAL) as z:
    smap = mod._shape_get_sheet_drawing_map(z)
    check("シート->drawing対応が正しく作られる",
          smap.get("Flow Chart") == ("xl/worksheets/sheet1.xml", "xl/drawings/drawing1.xml"),
          str(smap))
    droot = ET.fromstring(z.read("xl/drawings/drawing1.xml"))
    groups = mod._shape_extract_groups(droot)
    check("翻訳対象の図形数(記号のみの図形は除外される)", len(groups) == 2, f"{len(groups)}件")
    texts = sorted(g.original_text for g in groups)
    check("単一ラン図形のテキストが正しく抽出される",
          "Generate manhours and cost." in texts)
    check("複数ラン+複数段落図形のテキストが正しく抽出される(改行で連結)",
          "Generate the Manufacturing Plan. Use the Template.\nSecond line here" in texts,
          texts)


# ============================================================
# エンドツーエンド: openpyxl保存(図形消失) -> restore_and_translate_shapes
# ============================================================
shutil.copy2(ORIGINAL, OUTPUT)
wb = openpyxl.load_workbook(OUTPUT)
wb.save(OUTPUT)
wb.close()

with zipfile.ZipFile(OUTPUT) as z:
    check("openpyxl保存直後は図形が失われている(前提条件の確認)",
          not any("drawings" in n for n in z.namelist()))

CAPTURED["calls"].clear()
n_shapes = mod.restore_and_translate_shapes(ORIGINAL, OUTPUT, {"Flow Chart"}, "Japanese")
check("翻訳した図形数", n_shapes == 2, f"{n_shapes}件")
check("generate_advancedが呼ばれた(実際のtranslate_batch_parallel経由)",
      len(CAPTURED["calls"]) >= 1)

with zipfile.ZipFile(OUTPUT) as z:
    names = z.namelist()
    check("drawingパートが復元されている", "xl/drawings/drawing1.xml" in names)
    check("[Content_Types].xmlにdrawingのOverrideが追加されている",
          b"/xl/drawings/drawing1.xml" in z.read("[Content_Types].xml"))

    sheet_xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    check("sheet1.xmlに<drawing>参照が復元されている", "<drawing r:id=" in sheet_xml)
    check("sheet1.xmlのxmlns:r宣言が(無ければ)補われている(回帰テスト: "
          "未宣言のまま挿入すると不正なXMLになりLibreOffice/Excelが図形を"
          "黙って無視する不具合を実際に踏んで修正した)",
          "xmlns:r=" in sheet_xml.split(">", 1)[0])
    try:
        ET.fromstring(sheet_xml)
        sheet_xml_valid = True
    except ET.ParseError as e:
        sheet_xml_valid = False
        print(f"   ParseError: {e}")
    check("sheet1.xmlが妥当なXMLとしてパースできる(名前空間エラーが無い)", sheet_xml_valid)

    drawing_xml = z.read("xl/drawings/drawing1.xml").decode("utf-8")
    try:
        ET.fromstring(drawing_xml)
        drawing_xml_valid = True
    except ET.ParseError as e:
        drawing_xml_valid = False
        print(f"   ParseError: {e}")
    check("drawing1.xmlが妥当なXMLとしてパースできる", drawing_xml_valid)

    translated_texts = re.findall(r"<a:t>(.*?)</a:t>", drawing_xml)
    check("単一ラン図形の翻訳文が反映されている",
          any(t.startswith("YAKU:") and "manhours" in t for t in translated_texts), translated_texts)
    check("複数段落図形の1行目が翻訳されている",
          any("YAKU:" in t and "Manufacturing Plan" in t for t in translated_texts), translated_texts)
    check("複数段落図形の2行目(Second line here)も欠落せず翻訳されている",
          any("YAKU:" in t and "Second line here" in t for t in translated_texts), translated_texts)
    check("記号のみの図形(-)は翻訳されず原文のまま残る",
          any(t.strip() == "-" for t in translated_texts), translated_texts)

    ct_root = ET.fromstring(z.read("[Content_Types].xml"))
    check("[Content_Types].xmlも妥当なXMLとしてパースできる", ct_root is not None)

check("ZIP自体が壊れていない(testzip)",
      zipfile.ZipFile(OUTPUT).testzip() is None)


# ============================================================
# 図形の無いシート・翻訳対象外シートの扱い
# ============================================================
n_none = mod.restore_and_translate_shapes(ORIGINAL, OUTPUT, set(), "Japanese")
# sheet_names を空にした場合、翻訳はされないが図形の復元(原文のまま)は行われる仕様
with zipfile.ZipFile(OUTPUT) as z:
    check("翻訳対象シートを指定しない場合、図形は翻訳されず0件と返る", n_none == 0, f"{n_none}件")


# ============================================================
# LibreOfficeが使える環境では実際にレンダリングして確認する
# ============================================================
soffice = shutil.which("soffice")
if soffice:
    shutil.copy2(ORIGINAL, OUTPUT)
    wb = openpyxl.load_workbook(OUTPUT)
    wb.save(OUTPUT)
    wb.close()
    mod.restore_and_translate_shapes(ORIGINAL, OUTPUT, {"Flow Chart"}, "Japanese")

    pdf_path = os.path.join(WORKDIR, "shape_test_out.pdf")
    try:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", WORKDIR, OUTPUT],
                       capture_output=True, timeout=60, check=True)
        rendered_ok = os.path.exists(pdf_path)
    except Exception as e:
        rendered_ok = False
        print(f"   LibreOffice変換エラー: {e}")
    check("LibreOfficeでの変換が成功する(壊れたファイルとして拒否されない)", rendered_ok)

    if rendered_ok:
        pdftotext = shutil.which("pdftotext")
        if pdftotext:
            txt = subprocess.run([pdftotext, pdf_path, "-"], capture_output=True, text=True).stdout
            txt_nospace = txt.replace("\n", "").replace(" ", "")
            check("LibreOfficeでのレンダリング結果に翻訳文が実際に含まれる(実描画確認)",
                  "YAKU" in txt_nospace and "manhours" in txt_nospace, txt[:200])
        else:
            print("   (pdftotext未導入のためテキスト抽出による確認はスキップ)")
else:
    print("SKIP: LibreOffice(soffice)が無い環境のため実描画確認は省略")

shutil.rmtree(WORKDIR, ignore_errors=True)

# ============================================================
print("\n" + "=" * 60)
failed = [r for r in RESULTS if not r[1]]
print(f"合計 {len(RESULTS)} 項目 / 合格 {len(RESULTS) - len(failed)} / 失敗 {len(failed)}")
if failed:
    for name, _ok, detail in failed:
        print(f"  FAILED: {name}  {detail}")
sys.exit(1 if failed else 0)
