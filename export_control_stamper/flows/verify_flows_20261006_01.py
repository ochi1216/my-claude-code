#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_flows_20261006_01.py の生成物を、テナントへ入れずに検証する。

このフローはWindows / Power Automate 環境でしか実行できず、開発しているリモート
セッション(Linuxコンテナ)からはインポートも実行もできない。そこで、生成された
フロー定義(JSON)そのものを機械的に点検する。インポートで弾かれる典型的な間違い、
実行時に値が壊れる典型的な間違い、式の組み立てミスを対象にする。

実機での動作確認の代わりにはならない(operationId・パラメータ名・戻り値の形は、
ここではダミー値で見ているだけ)。「インポートして初めて気づく」類の失敗を潰すためのもの。

使い方(このフォルダで実行する。deploy_config.json は不要):

    python verify_flows_20261006_01.py

確認する項目:

  A. 設定の検査: 未実測の値があると生成が止まる / dryRun=true では差し替え用の実測値を求めない
  B. 構造: runAfter の参照先・アクション名の一意性・変数の初期化・Terminate/変数の置き場所
  C. 式: 括弧と引用符の釣り合い・未知の関数名・プレースホルダの残り
  D. 式の評価: メール本文から項目IDを取り出す式、カードを壊さない文字列変換、255文字の切り詰め
  E. 安全設計: dryRun では添付を差し替えるアクションが無い / 本番では元ファイルの退避が先
  F. 診断性: コネクタのアクションが SCOPE_Main の直下に並ぶ / Catch が失敗アクションを特定する
  G. 通知: 止まる経路が、通知してから終了する / カードのJSONが壊れない
  H. Solution: ファイル構成・XML・参照パス(先頭スラッシュ)・RootComponent
"""

import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CARDS = os.path.join(ROOT, "cards")
BUILD = os.path.join(HERE, "build_flows_20261006_01.py")

FAILURES = []
CHECKS = [0]


def check(ok, label, detail=""):
    CHECKS[0] += 1
    if ok:
        print("  ok   %s" % label)
    else:
        print("  NG   %s  %s" % (label, detail))
        FAILURES.append(label)


def load_builder():
    spec = importlib.util.spec_from_file_location("build_flows_20261006_01", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


b = load_builder()


# ---- ダミー設定(実値は使わない。構造だけを見る) -----------------------------------

def op(operation_id, **params):
    return {"operationId": operation_id, "params": {k: v for k, v in params.items()}}


def base_config(dry_run=True):
    return {
        "dryRun": dry_run,
        "sharePointSiteUrl": "https://example.sharepoint.com/sites/Dummy",
        "notifyRecipient": "tester@example.com",
        "mail": {"senderAddress": "flow-noreply@microsoft.com",
                 "subjectPrefix": "[Approval request] 該非判定", "folderPath": "Inbox"},
        "requestList": {"listId": "11111111-1111-1111-1111-111111111111",
                        "urlPath": "/Lists/Req",
                        "linkMarker": "/Lists/Req/DispForm.aspx?ID="},
        "attachment": {"certificateSuffix": "_該非判定証明書.xlsx"},
        "libraries": {"workFolderPath": "/sites/Dummy/Work"},
        "stampImagePath": "/sites/Dummy/Stamp/stamp.png",
        "script": {"sheetName": "該非判定証明書", "anchorCell": "H15", "approverName": "越智泰造",
                   "shapeName": "ECS_ApproverStamp", "targetWidthPt": 0, "targetHeightPt": 0,
                   "offsetXPt": 0, "offsetYPt": 0},
        "logList": {"listId": "22222222-2222-2222-2222-222222222222",
                    "columns": {"Title": "Title", "ProcessingStatus": "field_4",
                                "ErrorCode": "field_5", "ErrorDetail": "field_6"}},
        "connectionReferences": {"outlook": "njp_o365_dummy", "sharepoint": "njp_sp_dummy",
                                 "excel": "njp_excel_dummy", "teams": "njp_teams_dummy"},
        "workflowIds": {b.FLOW_NAME: "33333333-4444-5555-6666-777777777777"},
        "solution": {"uniqueName": "DummySolution", "publisherUniqueName": "NexperiaJP",
                     "publisherPrefix": "njp"},
        "measured": {
            "authentication": "@parameters('$authentication')",
            "mailTrigger": {"operationId": "DummyOnMail", "type": "OpenApiConnectionNotification",
                            "params": {"folderPath": "pFolder", "from": "pFrom",
                                       "subjectFilter": "pSubject"}},
            "expressions": {
                "triggerSubject": "@triggerOutputs()?['body/subject']",
                "triggerFrom": "@triggerOutputs()?['body/from']",
                "triggerBody": "@triggerOutputs()?['body/body']",
                "attachmentList": "@body('GET_Attachments')",
                "attachmentContent": "@body('GET_Attachment_Content')",
                "createdFileId": "@body('CREATE_Work_File')?['Id']",
                "stampBase64": "@body('GET_Stamp_Image')?['$content']",
                "scriptResult": "@body('RUN_Script')?['result']",
                "stampedContent": "@body('GET_Stamped_Content')",
            },
            "attachmentFields": {"id": "Id", "name": "DisplayName"},
            "getAttachments": op("DummyGetAttachments", dataset="d", table="t", itemId="i"),
            "getAttachmentContent": op("DummyGetContent", dataset="d", table="t", itemId="i",
                                       attachmentId="a"),
            "createFile": op("DummyCreateFile", dataset="d", folderPath="f", name="n", body="b"),
            "getFileContentByPath": op("DummyGetByPath", dataset="d", path="p"),
            "runScript": {
                "operationId": "DummyRunScript", "source": "SRC", "drive": "DRV",
                "scriptReference": "SCRIPT-REF",
                "params": {k: "sp_" + k for k in b.RUN_SCRIPT_PARAMS},
            },
            "getFileContent": op("DummyGetContentById", dataset="d", id="i"),
            "deleteAttachment": op("DummyDeleteAttachment", dataset="d", table="t", itemId="i",
                                   attachmentId="a"),
            "addAttachment": op("DummyAddAttachment", dataset="d", table="t", itemId="i",
                                name="n", body="b"),
        },
    }


def build(cfg):
    return b.build_flow(cfg, CARDS)


def definition_of(flow):
    return flow["properties"]["definition"]


# ---- 汎用の走査 ------------------------------------------------------------------

def walk(actions, scope=()):
    """(所属スコープのパス, 名前, アクション) を、入れ子も含めて順に返す。"""
    for name, action in actions.items():
        yield scope, name, action
        children = []
        if "actions" in action:
            children.append(("actions", action["actions"]))
        if "else" in action:
            children.append(("else", action["else"].get("actions", {})))
        for label, child in children:
            yield from walk(child, scope + ((name, label),))


def all_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from all_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from all_strings(value)


def container_of(actions_root, scope):
    node = actions_root
    for name, label in scope:
        action = node[name]
        node = action["actions"] if label == "actions" else action["else"]["actions"]
    return node


# ---- 簡易な式インタプリタ(式の評価の検証用。実際に使う関数だけ) ------------------

class Evaluator:
    def __init__(self, outputs):
        self.outputs = outputs

    def tokenize(self, text):
        tokens, i = [], 0
        while i < len(text):
            ch = text[i]
            if ch.isspace():
                i += 1
            elif ch in "(),":
                tokens.append((ch, ch))
                i += 1
            elif ch == "'":
                j, buf = i + 1, []
                while True:
                    if j >= len(text):
                        raise ValueError("文字列リテラルが閉じていません")
                    if text[j] == "'":
                        if j + 1 < len(text) and text[j + 1] == "'":
                            buf.append("'")
                            j += 2
                            continue
                        break
                    buf.append(text[j])
                    j += 1
                tokens.append(("str", "".join(buf)))
                i = j + 1
            elif ch.isdigit():
                j = i
                while j < len(text) and text[j].isdigit():
                    j += 1
                tokens.append(("num", int(text[i:j])))
                i = j
            elif ch.isalpha() or ch == "_":
                j = i
                while j < len(text) and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                tokens.append(("id", text[i:j]))
                i = j
            else:
                raise ValueError("想定外の文字: %r" % ch)
        return tokens

    def evaluate(self, text):
        self.tokens = self.tokenize(text)
        self.pos = 0
        value = self.parse()
        if self.pos != len(self.tokens):
            raise ValueError("式の後ろに余りがあります")
        return value

    def parse(self):
        kind, value = self.tokens[self.pos]
        self.pos += 1
        if kind in ("str", "num"):
            return value
        if kind != "id":
            raise ValueError("式の始まりが不正です")
        if self.tokens[self.pos][0] != "(":
            raise ValueError("関数呼び出しの括弧がありません: " + value)
        self.pos += 1
        args = []
        if self.tokens[self.pos][0] != ")":
            while True:
                args.append(self.parse())
                if self.tokens[self.pos][0] == ",":
                    self.pos += 1
                    continue
                break
        if self.tokens[self.pos][0] != ")":
            raise ValueError("括弧が閉じていません")
        self.pos += 1
        return self.call(value, args)

    def call(self, name, a):
        text = lambda v: "" if v is None else str(v)  # noqa: E731
        if name == "outputs":
            return self.outputs[a[0]]
        if name == "coalesce":
            return next((v for v in a if v is not None), None)
        if name == "string":
            return text(a[0])
        if name == "split":
            return text(a[0]).split(a[1])
        if name == "first":
            return a[0][0] if isinstance(a[0], list) else a[0][0:1]
        if name == "last":
            return a[0][-1] if isinstance(a[0], list) else a[0][-1:]
        if name == "trim":
            return text(a[0]).strip()
        if name == "int":
            return int(a[0])
        if name == "replace":
            return text(a[0]).replace(a[1], a[2])
        if name == "decodeUriComponent":
            return unquote(a[0])
        if name == "length":
            return len(a[0])
        if name == "substring":
            return text(a[0])[a[1]:a[1] + a[2]]
        if name == "concat":
            return "".join(text(v) for v in a)
        if name == "greater":
            return a[0] > a[1]
        if name == "if":
            return a[1] if a[0] else a[2]
        raise ValueError("このインタプリタが未対応の関数: " + name)


KNOWN_FUNCTIONS = {
    "variables", "outputs", "body", "triggerOutputs", "coalesce", "concat", "split", "first",
    "last", "trim", "int", "string", "json", "length", "substring", "replace",
    "decodeUriComponent", "uriComponent", "if", "greater", "equals", "contains", "startsWith",
    "endsWith", "toLower", "formatDateTime", "utcNow", "workflow", "result", "item", "parameters",
}


def expression_segments(text):
    """文字列から、式の部分('@式' 全体、または '@{式}' の中身)を取り出す。"""
    if text.startswith("@") and not text.startswith("@{"):
        yield text[1:]
        return
    index = 0
    while True:
        start = text.find("@{", index)
        if start < 0:
            return
        depth, i, in_str = 1, start + 2, False
        while i < len(text) and depth:
            ch = text[i]
            if ch == "'":
                if in_str and i + 1 < len(text) and text[i + 1] == "'":
                    i += 1
                else:
                    in_str = not in_str
            elif not in_str:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
            i += 1
        yield text[start + 2:i - 1]
        index = i


def check_expression(expression):
    """括弧・引用符の釣り合いと、関数名を確かめる。問題があれば説明を返す。"""
    depth, in_str, i = 0, False, 0
    names = []
    token = ""
    while i < len(expression):
        ch = expression[i]
        if in_str:
            if ch == "'":
                if i + 1 < len(expression) and expression[i + 1] == "'":
                    i += 1
                else:
                    in_str = False
        else:
            if ch == "'":
                in_str = True
                token = ""
            elif ch == "(":
                if token:
                    names.append(token)
                depth += 1
                token = ""
            elif ch == ")":
                depth -= 1
                token = ""
                if depth < 0:
                    return "閉じ括弧が多い: " + expression
            elif ch.isalnum() or ch == "_":
                token += ch
            else:
                token = ""
        i += 1
    if in_str:
        return "引用符が閉じていない: " + expression
    if depth != 0:
        return "括弧が釣り合っていない: " + expression
    unknown = sorted(set(n for n in names if n not in KNOWN_FUNCTIONS))
    if unknown:
        return "未知の関数 %s: %s" % (unknown, expression)
    return ""


# ---- 検証本体 --------------------------------------------------------------------

def section_a_config():
    print("A. 設定の検査")
    check(b.check_config(base_config(True)) == [], "ダミーの完全な設定(dryRun)は問題なしと判定される")
    check(b.check_config(base_config(False)) == [], "ダミーの完全な設定(本番)は問題なしと判定される")

    example_path = os.path.join(ROOT, "deploy_config.example.json")
    with open(example_path, encoding="utf-8") as fh:
        example = json.load(fh)
    problems = b.check_config(example)
    check(len(problems) > 20, "未実測だらけの example 設定では、多数の未実測を検出する",
          "検出数=%d" % len(problems))
    joined = "\n".join(problems)
    check("measured.mailTrigger.operationId" in joined, "未実測の operationId を名指しで一覧に出す")
    check("measured.deleteAttachment" not in joined and "measured.addAttachment" not in joined,
          "dryRun=true の間は、差し替え用(削除・追加)の実測値を求めない")
    example_prod = copy.deepcopy(example)
    example_prod["dryRun"] = False
    check("measured.deleteAttachment.operationId" in "\n".join(b.check_config(example_prod)),
          "dryRun=false にすると、差し替え用の実測値も求める")

    # 1つだけ未実測に戻すと、必ず検出される
    for dotted in ("measured.runScript.operationId", "measured.expressions.scriptResult",
                   "requestList.linkMarker", "stampImagePath", "logList.listId"):
        cfg = base_config(True)
        node = cfg
        keys = dotted.split(".")
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = "<未実測>"
        check(any(dotted in p for p in b.check_config(cfg)), "%s が未実測なら検出する" % dotted)

    cfg = base_config(True)
    cfg["logList"]["listId"] = "00000000-0000-0000-0000-000000000000"
    check(any("logList.listId" in p for p in b.check_config(cfg)), "全ゼロのGUIDは未実測として弾く")

    cfg = base_config(True)
    cfg["measured"]["expressions"]["scriptResult"] = "body('RUN_Script')"
    check(any("先頭が @" in p for p in b.check_config(cfg)), "式の先頭が @ でなければ指摘する")

    cfg = base_config(True)
    cfg["script"]["targetWidthPt"] = "50"
    check(any("targetWidthPt" in p for p in b.check_config(cfg)), "サイズが数値でなければ指摘する")


def section_cli():
    print("CLI: 未実測のままでは、何も出力せず止まる")
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "src")
        example = os.path.join(ROOT, "deploy_config.example.json")
        result = subprocess.run(
            [sys.executable, BUILD, "--config", example, "--out", out, "--cards", CARDS],
            capture_output=True, text=True, encoding="utf-8")
        check(result.returncode == 1, "終了コードが 1 になる", "rc=%s" % result.returncode)
        check("未実測" in result.stdout and "MEASUREMENT_GUIDE" in result.stdout,
              "未実測の一覧と、実測手順の案内を表示する")
        check(not os.path.exists(out), "出力フォルダを作らない(中途半端な生成物を残さない)")


def section_structure(label, flow):
    print("B/C. 構造と式 (%s)" % label)
    definition = definition_of(flow)
    actions = definition["actions"]

    names = [name for _scope, name, _action in walk(actions)]
    dups = sorted(set(n for n in names if names.count(n) > 1))
    check(not dups, "アクション名がフロー全体で一意", str(dups))

    bad_refs = []
    for scope, name, action in walk(actions):
        container = container_of(actions, scope)
        for ref in action.get("runAfter", {}):
            if ref not in container:
                bad_refs.append("%s -> %s" % (name, ref))
    check(not bad_refs, "すべての runAfter が、同じ階層に実在するアクションを指す", str(bad_refs))

    check(all(name in ("INIT_varItemId", "SCOPE_Main", "SCOPE_Catch") for name in actions),
          "最上位は INIT_varItemId / SCOPE_Main / SCOPE_Catch だけ")
    nested_init = [n for scope, n, a in walk(actions)
                   if a["type"] == "InitializeVariable" and scope]
    check(not nested_init, "InitializeVariable が最上位にしか無い", str(nested_init))

    initialized = {"varItemId"}
    used = set()
    for text in all_strings(definition):
        used.update(re.findall(r"variables\('(\w+)'\)", text))
    check(used <= initialized, "参照している変数がすべて初期化済み", str(used - initialized))

    loops = [n for _s, n, a in walk(actions) if a["type"] in ("Foreach", "Until")]
    check(not loops, "ループが無い(Terminate・変数をループ内に置く問題が起きない)")

    problems = []
    for text in all_strings(definition):
        for segment in expression_segments(text):
            message = check_expression(segment)
            if message:
                problems.append(message)
    check(not problems, "すべての式で、括弧・引用符が釣り合い、関数名が既知", "; ".join(problems[:3]))

    dumped = json.dumps(flow, ensure_ascii=False)
    check("未実測" not in dumped and not re.search(r"<[^<>\s']{1,60}>", dumped),
          "生成物にプレースホルダ(<...>・未実測)が残っていない")

    refs = flow["properties"]["connectionReferences"]
    check(sorted(refs) == ["shared_excelonlinebusiness", "shared_office365",
                           "shared_sharepointonline", "shared_teams"],
          "接続参照が4つ(Outlook / SharePoint / Excel Online / Teams)")
    check(all(r["runtimeSource"] == "tenant" for r in refs.values()),
          "接続参照はすべて tenant(自動実行のフローで invoker は使えない)")
    used_connections = {
        a["inputs"]["host"]["connectionName"]
        for _s, _n, a in walk(actions) if a["type"] == "OpenApiConnection"
    } | {definition["triggers"]["TRG_On_Approval_Mail"]["inputs"]["host"]["connectionName"]}
    check(used_connections <= set(refs), "使っているコネクタが、すべて接続参照に載っている",
          str(used_connections - set(refs)))


def section_safety(flow_dry, flow_prod):
    print("E. 安全設計")
    dry = definition_of(flow_dry)["actions"]["SCOPE_Main"]["actions"]
    prod = definition_of(flow_prod)["actions"]["SCOPE_Main"]["actions"]

    replace_names = {"GET_Stamped_Content", "DEL_Attachment", "ADD_Attachment"}
    check(not (replace_names & set(dry)),
          "dryRun=true では、添付を差し替えるアクションを生成しない(実行時の分岐ではなく生成時の切替)")
    check(replace_names <= set(prod), "dryRun=false では、差し替えのアクションを生成する")

    order = list(prod)
    check(order.index("CREATE_Backup_File") < order.index("RUN_Script"),
          "元ファイルの退避(_orig)は、押印より前")
    check(order.index("CREATE_Backup_File") < order.index("DEL_Attachment"),
          "元ファイルの退避は、添付の削除より前")
    check(order.index("GET_Stamped_Content") < order.index("DEL_Attachment") < order.index("ADD_Attachment"),
          "押印済みの内容を取得 → 元の添付を削除 → 追加 の順")
    check(order.index("CHK_Script_Stamped") < order.index("GET_Stamped_Content"),
          "押印が成功と確認できてから、差し替えに進む")
    check(order.index("ADD_Attachment") < order.index("LOG_Done"),
          "記録(Done)は、差し替えが済んでから")

    check(order.index("GET_Processed") < order.index("GET_Attachments"),
          "処理済みの確認は、添付の取得より前(二重処理の防止)")
    check(order.index("CHK_Valid_Mail") < order.index("GET_Processed"),
          "メールの検証は、処理より前")

    # 作業コピーに対してだけ押印する: RUN_Script の対象ファイルは、複製した作業ファイルのID
    run_file_value = dry["RUN_Script"]["inputs"]["parameters"]["sp_file"]
    check("CREATE_Work_File" in run_file_value and "CREATE_Backup_File" not in run_file_value,
          "押印の対象は作業コピーで、元の添付や退避ファイルではない")

    def status_param(flow):
        main = definition_of(flow)["actions"]["SCOPE_Main"]["actions"]
        return main["LOG_Done"]["inputs"]["parameters"]["item/field_4"]
    check(status_param(flow_dry) == "DryRunDone" and status_param(flow_prod) == "Done",
          "記録の状態: dryRun は DryRunDone、本番は Done(DryRunDone では再処理を妨げない)")
    processed_filter = dry["GET_Processed"]["inputs"]["parameters"]["$filter"]
    check("'Done'" in processed_filter and "DryRunDone" not in processed_filter,
          "処理済みの判定は Done だけ(dryRun を何度でも試せる)")

    # 記録のタイトルと、処理済みの判定が使うタイトルが食い違うと、二重処理の防止が
    # 静かに効かなくなる(記録は残るのに、次回それを見つけられない)
    done_title = dry["LOG_Done"]["inputs"]["parameters"]["item/Title"]
    check("'ECS-'" in done_title and "ECS-@{variables('varItemId')}" in processed_filter,
          "記録のタイトル(ECS-<ID>)と、処理済みの判定が探すタイトルが一致する")
    stop_titles = [
        a["inputs"]["parameters"]["item/Title"]
        for _s, n, a in walk(definition_of(flow_dry)["actions"]["SCOPE_Main"]["actions"])
        if n.startswith("LOG_") and n != "LOG_Done"
    ]
    check(stop_titles and all("'ECS-'" in t for t in stop_titles),
          "止めた経路の記録も、同じ ECS- 形式のタイトルで残す")

    expression = dry["CHK_Valid_Mail"]["expression"]["and"]
    flat = json.dumps(expression, ensure_ascii=False)
    check("flow-noreply@microsoft.com" in flat and "[Approval request] 該非判定" in flat,
          "メールの検証で、送信元と件名の先頭の両方を見る")
    check(dry["CHK_Valid_Mail"]["else"]["actions"]["END_Not_Target"]["inputs"]["runStatus"] == "Succeeded",
          "対象外のメールは、失敗にせず静かに終了する")


def section_diagnosability(flow):
    print("F. 診断性(失敗したアクションが分かる)")
    definition = definition_of(flow)["actions"]
    main = definition["SCOPE_Main"]["actions"]
    catch = definition["SCOPE_Catch"]

    check(catch["runAfter"] == {"SCOPE_Main": ["Failed", "TimedOut"]},
          "SCOPE_Catch は SCOPE_Main の Failed / TimedOut のときだけ動く")
    check(not any(a["type"] == "Scope" for a in main.values()),
          "SCOPE_Main の中にスコープの入れ子が無い(result() が直下の結果を返すため)")

    # メインの経路にあるコネクタのアクションは、すべて SCOPE_Main の直下
    in_branch_connectors = [
        name for scope, name, a in walk(main)
        if scope and a["type"] in ("OpenApiConnection", "OpenApiConnectionWebhook")
    ]
    check(all(re.match(r"(NTF|LOG)_", n) for n in in_branch_connectors),
          "If の枝の中にあるコネクタのアクションは、通知と記録だけ", str(in_branch_connectors))
    connectors_direct = [n for n, a in main.items() if a["type"] == "OpenApiConnection"]
    check({"GET_Processed", "GET_Attachments", "RUN_Script", "CREATE_Work_File"} <= set(connectors_direct),
          "処理の本体のコネクタ(取得・複製・押印)が SCOPE_Main の直下に並ぶ")

    catch_actions = catch["actions"]
    check(catch_actions["FLT_Failed_Actions"]["inputs"]["from"] == "@result('SCOPE_Main')",
          "Catch が result('SCOPE_Main') から失敗したアクションを取り出す")
    check("Failed" in json.dumps(catch_actions["FLT_Failed_Actions"]["inputs"]["where"]),
          "取り出すのは status が Failed のもの")
    check("'name'" in catch_actions["CMP_Error_Raw"]["inputs"]
          and "'message'" in catch_actions["CMP_Error_Raw"]["inputs"],
          "記録するのは、失敗したアクション名とメッセージ")
    end = catch_actions["END_Failed"]
    check(end["type"] == "Terminate" and end["inputs"]["runStatus"] == "Failed",
          "最後は Terminate(Failed) で、実行履歴が失敗として残る")
    check(end["runAfter"] == {"NTF_Error": b.ALL_STATUSES},
          "通知が失敗しても、必ず失敗で終了する")
    check(catch_actions["NTF_Error"]["runAfter"] == {"LOG_Error": b.ALL_STATUSES},
          "記録が失敗しても、通知は行う")
    check("make.powerautomate.com" in json.dumps(
        catch_actions["NTF_Error"]["inputs"]["parameters"], ensure_ascii=False),
          "通知に、フローの実行履歴へのリンクを含める")


def section_notify(flow):
    print("G. 通知とカード")
    main = definition_of(flow)["actions"]["SCOPE_Main"]["actions"]

    # 止まる経路: 通知 → 記録 → 終了 の順で、Terminate の前に通知がある
    stop_branches = []
    for name, action in main.items():
        if action["type"] == "If" and action["else"]["actions"]:
            stop_branches.append((name, action["else"]["actions"]))
    check(len(stop_branches) >= 5, "検証で止める経路が揃っている(対象外・リンク・処理済み・証明書・押印)",
          "数=%d" % len(stop_branches))
    for name, branch in stop_branches:
        keys = list(branch)
        terminates = [k for k in keys if branch[k]["type"] == "Terminate"]
        if name == "CHK_Valid_Mail":
            check(len(terminates) == 1, "%s: 対象外メールは Terminate のみ(通知なし)" % name)
            continue
        notify_keys = [k for k in keys if k.startswith("NTF_")]
        ordered = keys.index(terminates[0]) > max([keys.index(k) for k in notify_keys] or [-1])
        # 名前だけでなく、実体が Teams のカード投稿であること(別のアクションに差し替わっていないこと)
        real_notice = bool(notify_keys) and all(
            branch[k]["type"] == "OpenApiConnection"
            and branch[k]["inputs"]["host"]["connectionName"] == "shared_teams"
            and branch[k]["inputs"]["host"]["operationId"] == "PostCardToConversation"
            for k in notify_keys)
        check(len(terminates) == 1 and ordered and real_notice,
              "%s: Teams へ通知してから終了する" % name)
        if name != "CHK_Not_Processed":
            log_keys = [k for k in keys if k.startswith("LOG_")]
            check(bool(log_keys) and all(
                branch[k]["inputs"]["host"]["operationId"] == "PostItem" for k in log_keys),
                "%s: 記録(PostItem)も残す" % name)
        failed_status = branch[terminates[0]]["inputs"]["runStatus"]
        expected = "Succeeded" if name == "CHK_Not_Processed" else "Failed"
        check(failed_status == expected, "%s: 終了状態は %s" % (name, expected))

    # カードのJSON: @{...} をダミーに置換すると、有効なJSONとして読める
    broken = []
    for _scope, name, action in walk(main):
        if action["type"] != "OpenApiConnection":
            continue
        card = action["inputs"]["parameters"].get("body/messageBody")
        if card is None:
            continue
        stripped = card
        for segment in expression_segments(card):
            stripped = stripped.replace("@{" + segment + "}", "X")
        try:
            parsed = json.loads(stripped)
            if "${" in card:
                broken.append(name + ": ${ が残っている")
            if parsed.get("type") != "AdaptiveCard":
                broken.append(name + ": AdaptiveCard ではない")
        except ValueError as error:
            broken.append("%s: %s" % (name, error))
    check(not broken, "すべてのカードが、式を除くと有効なJSONで、プレースホルダが残っていない", str(broken))


def section_expressions():
    print("D. 式の評価(簡易インタプリタで実際に動かす)")
    marker = "/Lists/Parameter_sheet_request/DispForm.aspx?ID="
    expression = b.extract_item_id_expr(marker)

    def extract(body):
        return Evaluator({"CMP_Body": body}).evaluate(expression)

    html_cases = [
        ('<a href="https://x.sharepoint.com/sites/JapanDesign' + marker + '40&amp;Source=abc">リンク</a>', 40),
        ('<a href="https://x.sharepoint.com/sites/JapanDesign' + marker + '7">リンク</a>', 7),
        ("see https://x.sharepoint.com/sites/JapanDesign" + marker + "123 next", 123),
        ("<a href='https://x" + marker + "5'>x</a>", 5),
        ("https://x" + marker + "99#frag", 99),
        ("https://x" + marker + "8<br>", 8),
        ("先頭に日本語 https://x" + marker + "40&Conte...", 40),
    ]
    def attempt(body):
        """式が壊れていても検証全体が落ちないよう、例外は結果として返す。"""
        try:
            return extract(body)
        except (ValueError, IndexError, KeyError, TypeError) as error:
            return "ERROR: %s" % error

    for body, expected in html_cases:
        got = attempt(body)
        check(got == expected, "本文から項目IDを取り出せる: ...ID=%d" % expected, "got=%r" % (got,))

    # 同じマーカーが2か所にある場合は、最後のものを使う(last)。変な方を拾わないことの確認
    check(attempt("https://x" + marker + "1 and https://y" + marker + "2") == 2,
          "マーカーが複数ある場合は、最後のものを使う")
    try:
        extract("マーカーの無い本文")
        check(False, "マーカーが無い本文は、数値に変換できず失敗する(SCOPE_Catch で記録される)")
    except ValueError:
        check(True, "マーカーが無い本文は、数値に変換できず失敗する(SCOPE_Catch で記録される)")

    # カードを壊さない文字列変換
    text_expr = b.safe_text("outputs('MSG')")
    nasty = 'エラー: "引用符"\nと改行\tとタブ、バックスラッシュ \\ と\r\n復帰'
    safe = Evaluator({"MSG": nasty}).evaluate(text_expr)
    check('"' not in safe and "\\" not in safe and "\n" not in safe and "\r" not in safe
          and "\t" not in safe, "safe_text: 引用符・改行・タブ・バックスラッシュを除く", repr(safe))
    check(json.loads('{"t": "%s"}' % safe)["t"] == safe, "safe_text: 結果をそのままJSON文字列へ入れられる")
    check("エラー" in safe and "引用符" in safe, "safe_text: 本文の内容は残る")
    check('"' not in text_expr, "safe_text: 式そのものに二重引用符を含まない(カードの組み立てが壊れない)")

    # 255文字の切り詰め
    clip = b.clip255("outputs('MSG')")
    long_text = "あ" * 400
    clipped = Evaluator({"MSG": long_text}).evaluate(clip[1:])
    check(len(clipped) == 255 and clipped.endswith("..."), "clip255: 255文字に収め、末尾に ... を付ける")
    short = Evaluator({"MSG": "短い"}).evaluate(clip[1:])
    check(short == "短い", "clip255: 短い文字列はそのまま")

    # 文字列リテラルのエスケープ
    check(b.lit("it's") == "'it''s'", "lit: シングルクォートを '' に重ねる")


def section_mapping(flow):
    print("パラメータの対応")
    main = definition_of(flow)["actions"]["SCOPE_Main"]["actions"]
    run = main["RUN_Script"]["inputs"]
    check(run["host"]["operationId"] == "DummyRunScript" and run["host"]["apiId"].endswith("shared_excelonlinebusiness"),
          "RUN_Script は実測した operationId で、Excel Online コネクタを指す")
    params = run["parameters"]
    check(set(params) == {"sp_" + k for k in b.RUN_SCRIPT_PARAMS},
          "RUN_Script のパラメータ名は、実測した名前だけ(論理名が漏れない)")
    check(params["sp_source"] == "SRC" and params["sp_drive"] == "DRV" and params["sp_script"] == "SCRIPT-REF",
          "場所・ライブラリ・スクリプトの指定が、設定どおり入る")
    check(params["sp_anchorCell"] == "H15" and params["sp_approverName"] == "越智泰造"
          and params["sp_shapeName"] == "ECS_ApproverStamp",
          "押印位置・承認者名・図形名が、設定どおり入る")
    check(params["sp_targetWidthPt"] == 0 and params["sp_offsetXPt"] == 0,
          "サイズ・オフセットは数値のまま入る(文字列にならない)")

    trigger = definition_of(flow)["triggers"]["TRG_On_Approval_Mail"]
    check(trigger["type"] == "OpenApiConnectionNotification"
          and trigger["inputs"]["host"]["operationId"] == "DummyOnMail",
          "トリガーは実測した型と operationId")
    check(trigger["inputs"]["parameters"] == {
        "pFolder": "Inbox", "pFrom": "flow-noreply@microsoft.com", "pSubject": "[Approval request] 該非判定"},
        "トリガーの絞り込み(フォルダ・送信元・件名)が、実測したパラメータ名で入る")

    cfg = base_config(True)
    cfg["notifyRecipient"] = "other@example.com"
    other = build(cfg)
    dumped = json.dumps(other, ensure_ascii=False)
    check("other@example.com" in dumped and "tester@example.com" not in dumped,
          "通知先は設定の notifyRecipient だけから決まる")

    # SharePoint 実測済みの操作: 記録リストへの書き込みは、設定した列の内部名で行う
    log = main["LOG_Done"]["inputs"]
    check(log["host"]["operationId"] == "PostItem" and
          {"item/Title", "item/field_4", "item/field_5", "item/field_6"} <= set(log["parameters"]),
          "記録は PostItem で、設定した列の内部名へ書く")


def section_solution(flow):
    print("H. Solution の出力")
    cfg = base_config(True)
    with tempfile.TemporaryDirectory() as tmp:
        flows = {b.FLOW_NAME: (cfg["workflowIds"][b.FLOW_NAME], flow)}
        b.write_solution(tmp, cfg, flows)
        guid = cfg["workflowIds"][b.FLOW_NAME]
        base = "%s-%s" % (b.FLOW_NAME, guid.upper())
        json_path = os.path.join(tmp, "Workflows", base + ".json")
        xml_path = json_path + ".data.xml"
        check(os.path.exists(json_path) and os.path.exists(xml_path),
              "Workflows/<Name>-<GUID大文字>.json と .json.data.xml の組が出力される")
        with open(json_path, encoding="utf-8") as fh:
            check(json.load(fh) == flow, "フロー定義JSONが、そのまま読み戻せる")

        for relative in ("Other/Solution.xml", "Other/Customizations.xml",
                         "Other/Relationships.xml", "Workflows/%s.json.data.xml" % base):
            try:
                ET.parse(os.path.join(tmp, relative))
                check(True, "%s がXMLとして読める" % relative)
            except ET.ParseError as error:
                check(False, "%s がXMLとして読める" % relative, str(error))

        data = ET.parse(xml_path).getroot()
        check(data.findtext("JsonFileName") == "/Workflows/%s.json" % base,
              "JsonFileName は先頭スラッシュ付き(無いと Part URI エラーで取り込めない)")
        check(data.get("WorkflowId") == "{%s}" % guid.lower(), "WorkflowId は小文字GUID")

        solution = ET.parse(os.path.join(tmp, "Other", "Solution.xml")).getroot()
        components = [(c.get("type"), c.get("id")) for c in solution.iter("RootComponent")]
        check(components == [("29", "{%s}" % guid.lower())], "RootComponent は type=29 でフローを登録する")

        customizations = ET.parse(os.path.join(tmp, "Other", "Customizations.xml")).getroot()
        workflows = customizations.find("Workflows")
        check(workflows is not None and len(list(workflows)) == 0,
              "Customizations.xml の <Workflows /> は空のまま(ここに書くと pack が無視する)")


def guard(section, *args):
    """検証の途中で例外が出ても、検証全体を落とさず、失敗として報告する。"""
    try:
        section(*args)
    except Exception as error:  # noqa: BLE001 - 検証の対象が壊れている場合を含むため広く受ける
        check(False, "%s が最後まで実行できた" % section.__name__,
              "%s: %s" % (type(error).__name__, error))


def section_summarizer(flow):
    print("要約ツール(summarize_export)")
    spec = importlib.util.spec_from_file_location(
        "summarize_export_20261006_01", os.path.join(HERE, "summarize_export_20261006_01.py"))
    summarizer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(summarizer)

    cfg = base_config(True)
    with tempfile.TemporaryDirectory() as tmp:
        b.write_solution(tmp, cfg, {b.FLOW_NAME: (cfg["workflowIds"][b.FLOW_NAME], flow)})
        text = summarizer.summarize(tmp)

    check("DummyRunScript" in text and "DummyOnMail" in text and "DummyCreateFile" in text,
          "operationId を順に列挙する")
    check("sp_stampBase64" in text and "pFolder" in text, "パラメータ名(キー)は伏せずに出す")
    check("njp_excel_dummy" in text, "接続参照の論理名を出す")
    check("tester@example.com" not in text and "<email>" in text, "メールアドレスを伏せる")
    check("11111111-1111-1111-1111-111111111111" not in text and "<GUID>" in text, "GUIDを伏せる")
    check("example.sharepoint.com" not in text and "<host>" in text, "URLのホスト名を伏せる")
    check(text.index("CHK_Valid_Mail") < text.index("GET_Processed") < text.index("RUN_Script"),
          "アクションを実行順に並べる")


def main():
    print("== 設定とCLI ==")
    guard(section_a_config)
    guard(section_cli)
    print("")
    guard(section_expressions)

    try:
        flow_dry = build(base_config(True))
        flow_prod = build(base_config(False))
    except Exception as error:  # noqa: BLE001
        check(False, "ダミー設定からフローを生成できた", "%s: %s" % (type(error).__name__, error))
        print("%d 項目を確認 / 失敗 %d" % (CHECKS[0], len(FAILURES)))
        sys.exit(1)

    for label, flow in (("dryRun", flow_dry), ("本番", flow_prod)):
        print("")
        guard(section_structure, label, flow)
    print("")
    guard(section_safety, flow_dry, flow_prod)
    print("")
    guard(section_diagnosability, flow_dry)
    print("")
    guard(section_diagnosability, flow_prod)
    print("")
    guard(section_notify, flow_dry)
    print("")
    guard(section_mapping, flow_dry)
    print("")
    guard(section_solution, flow_dry)
    print("")
    guard(section_summarizer, flow_dry)

    print("")
    print("%d 項目を確認 / 失敗 %d" % (CHECKS[0], len(FAILURES)))
    if FAILURES:
        for label in FAILURES:
            print("  NG: " + label)
        sys.exit(1)
    print("すべて合格")


if __name__ == "__main__":
    main()
