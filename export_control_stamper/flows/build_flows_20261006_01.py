#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""該非判定の承認依頼メールを受けて、証明書に印影を挿入するフロー(JSON)を生成する。

手作業の流れ(メール → リンク → 添付のExcel → 印影挿入 → 保存)を、Power Automate の
クラウドフロー1本(ECS01_Stamp_On_Approval_Mail_DEV)に置き換える。最終承認ボタンは
人(越智さん)が押す。フローが行うのは、印影の挿入と、結果の通知まで。

出力される構造は、power_automate_safety_checkin/solution/build_flows_20260901_02.py と
同じ(Dataverse の実物からリバースエンジニアリングした形式。実機で動作確認済み):

    <out>/
      Other/Solution.xml · Other/Customizations.xml · Other/Relationships.xml
      Workflows/<Name>-<GUID大文字>.json
      Workflows/<Name>-<GUID大文字>.json.data.xml

使い方:

    python build_flows_20261006_01.py --config ../deploy_config.json --out ./src
    pac solution pack --zipfile ./ExportControlStamper.zip --folder ./src
    pac solution import --path ./ExportControlStamper.zip

設計上の約束事:

  1. 推測で作らない。 コネクタの operationId・パラメータ名・戻り値の形は、設定の
     `measured` に実測値が入るまで生成を止める(推測値はインポートが通ってしまい、
     実行時に初めて失敗するため)。未実測の項目は、まとめて一覧で表示する。
  2. dryRun が既定。 dryRun=true の間は、添付を差し替えるアクション自体を生成しない
     (実行時の分岐ではなく、生成時の切替)。実行履歴に残るのは、押印した作業コピーだけ。
  3. 失敗したアクションが分かる。 コネクタのアクションはすべて SCOPE_Main の直下に
     並べ、SCOPE_Catch で result('SCOPE_Main') から、失敗したアクション名とメッセージを
     取り出して記録・通知する(前回は、失敗した枝の名前までしか分からなかった)。
  4. 止まるときは、必ず通知してから止まる。 Terminate は SCOPE_Catch を通らないため、
     検証で止める経路(対象外・処理済み・証明書が無い・押印を中止)は、通知と記録を
     自分で行ってから終了する。
"""

import argparse
import json
import os
import re
import sys
from urllib.parse import urlparse

FLOW_NAME = "ECS01_Stamp_On_Approval_Mail_DEV"

SP_API = "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
TEAMS_API = "/providers/Microsoft.PowerApps/apis/shared_teams"
OUTLOOK_API = "/providers/Microsoft.PowerApps/apis/shared_office365"
EXCEL_API = "/providers/Microsoft.PowerApps/apis/shared_excelonlinebusiness"

ALL_STATUSES = ["Succeeded", "Failed", "Skipped", "TimedOut"]

# ---- 設定の検査 ------------------------------------------------------------------


def is_measured(value):
    """設定値が実測値で埋まっているか。

    <...> のプレースホルダが残っているもの・空文字は「未実測」。全ゼロのGUIDも弾く
    (書式としては正しく見えるが実在しないリストを指し、インポートは通ったうえで、
    フローを開いた時点で List not found になるため)。
    """
    if not (isinstance(value, str) and value.strip() != "" and "<" not in value):
        return False
    return value.strip().strip("{}").strip("0-") != ""


def get_path(cfg, dotted):
    node = cfg
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


RUN_SCRIPT_PARAMS = [
    "source", "drive", "file", "script", "stampBase64", "sheetName", "anchorCell",
    "approverName", "shapeName", "targetWidthPt", "targetHeightPt", "offsetXPt", "offsetYPt",
]

# (演算名, 必要なパラメータ名)
OPERATIONS = [
    ("getAttachments", ["dataset", "table", "itemId"]),
    ("getAttachmentContent", ["dataset", "table", "itemId", "attachmentId"]),
    ("createFile", ["dataset", "folderPath", "name", "body"]),
    ("getFileContentByPath", ["dataset", "path"]),
]
REPLACE_OPERATIONS = [
    ("getFileContent", ["dataset", "id"]),
    ("deleteAttachment", ["dataset", "table", "itemId", "attachmentId"]),
    ("addAttachment", ["dataset", "table", "itemId", "name", "body"]),
]
EXPRESSIONS = [
    "triggerSubject", "triggerFrom", "triggerBody", "attachmentList", "attachmentContent",
    "createdFileId", "stampBase64", "scriptResult",
]


def required_paths(dry_run):
    """生成に必要な設定値のパス一覧。dryRun=true では差し替え用の実測値を求めない。"""
    paths = [
        "sharePointSiteUrl", "notifyRecipient",
        "mail.senderAddress", "mail.subjectPrefix", "mail.folderPath",
        "requestList.listId", "requestList.urlPath", "requestList.linkMarker",
        "attachment.certificateSuffix", "libraries.workFolderPath", "stampImagePath",
        "script.sheetName", "script.anchorCell", "script.approverName", "script.shapeName",
        "logList.listId", "logList.columns.Title", "logList.columns.ProcessingStatus",
        "logList.columns.ErrorCode", "logList.columns.ErrorDetail",
        "connectionReferences.outlook", "connectionReferences.sharepoint",
        "connectionReferences.excel", "connectionReferences.teams",
        "workflowIds." + FLOW_NAME,
        "solution.uniqueName", "solution.publisherUniqueName", "solution.publisherPrefix",
        "measured.authentication",
        "measured.mailTrigger.operationId", "measured.mailTrigger.type",
        "measured.mailTrigger.params.folderPath", "measured.mailTrigger.params.from",
        "measured.mailTrigger.params.subjectFilter",
        "measured.attachmentFields.id", "measured.attachmentFields.name",
        "measured.runScript.operationId", "measured.runScript.source",
        "measured.runScript.drive", "measured.runScript.scriptReference",
    ]
    paths += ["measured.expressions." + name for name in EXPRESSIONS]
    paths += ["measured.runScript.params." + name for name in RUN_SCRIPT_PARAMS]
    operations = OPERATIONS + ([] if dry_run else REPLACE_OPERATIONS)
    for op, params in operations:
        paths.append("measured.%s.operationId" % op)
        paths += ["measured.%s.params.%s" % (op, p) for p in params]
    if not dry_run:
        paths.append("measured.expressions.stampedContent")
    return paths


def check_config(cfg):
    """未実測・不正な設定値を、まとめて一覧にして返す(空なら問題なし)。"""
    problems = []
    dry_run = cfg.get("dryRun", True)
    if not isinstance(dry_run, bool):
        problems.append("dryRun: true / false のどちらかにしてください")
        dry_run = True

    for path in required_paths(dry_run):
        if not is_measured(get_path(cfg, path)):
            problems.append("%s: 未実測または未設定です" % path)

    # 式は、先頭が @ の形で書く(Power Automate の式として評価されるため)
    for name in EXPRESSIONS + ([] if dry_run else ["stampedContent"]):
        value = get_path(cfg, "measured.expressions." + name)
        if is_measured(value) and not value.startswith("@"):
            problems.append("measured.expressions.%s: 先頭が @ の式で書いてください" % name)

    recipient = cfg.get("notifyRecipient", "")
    if is_measured(recipient) and "@" not in recipient:
        problems.append("notifyRecipient: メールアドレスの形式ではありません")

    script = cfg.get("script", {})
    for key in ("targetWidthPt", "targetHeightPt", "offsetXPt", "offsetYPt"):
        value = script.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append("script.%s: 数値にしてください" % key)
        elif key.startswith("target") and value < 0:
            problems.append("script.%s: 0 以上にしてください" % key)
    return problems


# ---- 式の部品 --------------------------------------------------------------------


def lit(text):
    """Power Automate の式の文字列リテラル。' は '' に重ねて書く。"""
    return "'" + text.replace("'", "''") + "'"


def strip_at(expression):
    """設定の式('@...')から先頭の @ を外す(別の式の中へ埋め込むため)。"""
    return expression[1:] if expression.startswith("@") else expression


def safe_text(expression):
    """自由記述の文字列を、Adaptive Card の JSON を壊さない形へ変える式を返す。

    例外メッセージなどには、引用符・改行・バックスラッシュが入りうる。これらが
    カードの JSON 文字列に入ると、カード全体が不正になり投稿に失敗する。
    式の中に " を直接書くとカードの組み立て自体が壊れるため、decodeUriComponent で作る。
    """
    expr = "string(%s)" % expression
    for code, replacement in (
        ("%5C", "/"),
        ("%22", "\u2019"),
        ("%0D", " "),
        ("%0A", " "),
        ("%09", " "),
    ):
        expr = "replace(%s, decodeUriComponent(%s), %s)" % (expr, lit(code), lit(replacement))
    return expr


def clip255(expression):
    """1行テキスト列の上限(255文字)に収める式('@' 付き)。超えると書き込み自体が失敗する。"""
    return (
        "@if(greater(length(string({e})), 255), concat(substring(string({e}), 0, 252), '...'), "
        "string({e}))".format(e=expression)
    )


def item_url_expr(cfg):
    """リクエスト(リスト項目)の表示画面のURLを作る式(@なし)。"""
    base = cfg["sharePointSiteUrl"].rstrip("/") + cfg["requestList"]["urlPath"]
    return "concat(%s, string(variables('varItemId')))" % lit(base + "/DispForm.aspx?ID=")


def run_url_expr():
    return (
        "concat('https://make.powerautomate.com/environments/', "
        "workflow()?['tags']?['environmentName'], '/flows/', workflow()?['name'], "
        "'/runs/', workflow()?['run']?['name'])"
    )


def extract_item_id_expr(marker):
    """メール本文から、マーカーの直後の項目IDを取り出す式(@なし)。

    式に正規表現は無いため、マーカー以降を取り、数字のあとに続きうる区切り文字で
    順に切り落とす。数字でなければ int() が失敗し、SCOPE_Catch で失敗として記録される。
    """
    expr = "last(split(coalesce(outputs('CMP_Body'), ''), %s))" % lit(marker)
    for sep in ["&", '"', "'", "<", ">", "#", " "]:
        expr = "first(split(%s, %s))" % (expr, lit(sep))
    return "int(trim(%s))" % expr


# ---- アクションの部品 ------------------------------------------------------------


def conn_action(api_id, connection_name, operation_id, parameters, run_after, auth,
                kind="OpenApiConnection"):
    return {
        "runAfter": run_after,
        "type": kind,
        "inputs": {
            "host": {
                "connectionName": connection_name,
                "operationId": operation_id,
                "apiId": api_id,
            },
            "parameters": parameters,
            "authentication": auth,
        },
    }


def mapped(op_cfg, values):
    """論理名 → 実測したパラメータ名へ置き換えて、アクションの parameters を作る。"""
    return {op_cfg["params"][logical]: value for logical, value in values.items()}


def terminate(status, run_after, code=None, message=None):
    inputs = {"runStatus": status}
    if status == "Failed":
        inputs["runError"] = {"code": code or "", "message": message or ""}
    return {"runAfter": run_after, "type": "Terminate", "inputs": inputs}


def compose(expression, run_after):
    return {"runAfter": run_after, "type": "Compose", "inputs": expression}


def after(name, statuses=None):
    return {name: statuses or ["Succeeded"]}


def load_card(cards_dir, filename, bindings):
    """カード(JSON)を読み込み、${Name} をフローの式 @{...} へ置換して、1行の文字列で返す。

    Power Automate はカード内の ${...} を解決しないため、投稿前に差し替える。
    """
    with open(os.path.join(cards_dir, filename), encoding="utf-8-sig") as fh:
        text = fh.read()

    def replace(match):
        key = match.group(1)
        if key not in bindings:
            raise KeyError("カード %s の ${%s} に対応する式が未定義です" % (filename, key))
        return bindings[key]

    text = re.sub(r"\$\{(\w+)\}", replace, text)
    return json.dumps(json.loads(text), ensure_ascii=False)


# ---- フロー本体 ------------------------------------------------------------------


def build_flow(cfg, cards_dir):
    dry_run = cfg.get("dryRun", True)
    measured = cfg["measured"]
    expr = measured["expressions"]
    auth = measured["authentication"]
    site_url = cfg["sharePointSiteUrl"]
    parsed = urlparse(site_url)
    site_origin = "%s://%s" % (parsed.scheme, parsed.netloc)
    request_list = cfg["requestList"]
    log_cols = cfg["logList"]["columns"]
    log_list_id = cfg["logList"]["listId"]
    script = cfg["script"]
    attach_fields = measured["attachmentFields"]
    mode_label = "DRY-RUN(添付は差し替えません)" if dry_run else "本番(添付を差し替えます)"
    recipient = cfg["notifyRecipient"]

    def sp(operation_id, parameters, run_after):
        # GetItems / PostItem は、安否確認ツールで実測済みの operationId
        return conn_action(SP_API, "shared_sharepointonline", operation_id, parameters,
                           run_after, auth)

    def sp_measured(op_name, values, run_after):
        op_cfg = measured[op_name]
        return conn_action(SP_API, "shared_sharepointonline", op_cfg["operationId"],
                           mapped(op_cfg, values), run_after, auth)

    def teams_card(card_text, run_after):
        # 1:1チャットへの投稿(応答を待たない版)。安否確認ツールで実機確認済みの形。
        return conn_action(
            TEAMS_API, "shared_teams", "PostCardToConversation",
            {
                "poster": "Flow bot",
                "location": "Chat with Flow bot",
                "body/recipient": recipient,
                "body/messageBody": card_text,
            },
            run_after, auth,
        )

    def log_item(title_expr, status, code_expr, detail_expr, run_after):
        return sp(
            "PostItem",
            {
                "dataset": site_url,
                "table": log_list_id,
                "item/%s" % log_cols["Title"]: title_expr,
                "item/%s" % log_cols["ProcessingStatus"]: status,
                "item/%s" % log_cols["ErrorCode"]: code_expr,
                "item/%s" % log_cols["ErrorDetail"]: detail_expr,
            },
            run_after,
        )

    item_id = "@{variables('varItemId')}"
    item_url = "@{%s}" % item_url_expr(cfg)
    run_url = "@{%s}" % run_url_expr()

    def notice_card(heading, status, detail_expr_no_at):
        return load_card(cards_dir, "stamp_notice_card.json", {
            "Heading": heading,
            "Mode": mode_label,
            "ItemId": item_id,
            "Status": status,
            "Detail": "@{%s}" % safe_text(detail_expr_no_at),
            "ItemUrl": item_url,
            "RunUrl": run_url,
        })

    def stop_branch(prefix, heading, status_expr_no_at, code_expr_no_at, detail_expr_no_at,
                    run_after, terminate_status="Failed"):
        """検証で止める経路。通知 → 記録 → 終了 の順に、必ず通知してから止まる。"""
        card = load_card(cards_dir, "stamp_notice_card.json", {
            "Heading": heading,
            "Mode": mode_label,
            "ItemId": item_id,
            "Status": "@{%s}" % safe_text(status_expr_no_at),
            "Detail": "@{%s}" % safe_text(detail_expr_no_at),
            "ItemUrl": item_url,
            "RunUrl": run_url,
        })
        return {
            "NTF_%s" % prefix: teams_card(card, run_after),
            "LOG_%s" % prefix: log_item(
                "@concat('ECS-', string(variables('varItemId')))",
                "Stopped",
                "@%s" % code_expr_no_at,
                clip255(detail_expr_no_at),
                after("NTF_%s" % prefix, ALL_STATUSES),
            ),
            "END_%s" % prefix: terminate(
                terminate_status,
                after("LOG_%s" % prefix, ALL_STATUSES),
                "ECS-STOP", heading,
            ),
        }

    attachment_name = "outputs('CMP_Attachment_Name')"
    main = {}
    previous = [None]

    def add(name, action_factory):
        """直前のアクションの成功を待つ形で、SCOPE_Main へ並べる。"""
        run_after = after(previous[0]) if previous[0] else {}
        main[name] = action_factory(run_after)
        previous[0] = name

    # 1. 受信メールの確認(コネクタ側の絞り込みに加えて、フロー内でも確かめる)
    add("CMP_Subject", lambda ra: compose(expr["triggerSubject"], ra))
    add("CMP_From", lambda ra: compose(expr["triggerFrom"], ra))
    add("CMP_Body", lambda ra: compose(expr["triggerBody"], ra))
    add("CHK_Valid_Mail", lambda ra: {
        "runAfter": ra,
        "type": "If",
        "expression": {"and": [
            {"startsWith": ["@coalesce(outputs('CMP_Subject'), '')", cfg["mail"]["subjectPrefix"]]},
            {"contains": ["@toLower(coalesce(string(outputs('CMP_From')), ''))",
                          cfg["mail"]["senderAddress"].lower()]},
        ]},
        "actions": {},
        "else": {"actions": {"END_Not_Target": terminate("Succeeded", {})}},
    })

    # 2. 本文のリンクからリクエストIDを取り出す
    add("CHK_Link_Found", lambda ra: {
        "runAfter": ra,
        "type": "If",
        "expression": {"contains": ["@coalesce(outputs('CMP_Body'), '')",
                                    request_list["linkMarker"]]},
        "actions": {},
        "else": {"actions": stop_branch(
            "Link_Missing", "メール本文にリクエストへのリンクが見つかりません",
            "'LinkNotFound'", "'LinkNotFound'",
            lit("本文に「%s」を含むリンクがありません。メールの形式が変わった可能性があります。"
                % request_list["linkMarker"]),
            {},
        )},
    })
    add("CMP_Item_Id", lambda ra: compose("@" + extract_item_id_expr(request_list["linkMarker"]), ra))
    add("SET_varItemId", lambda ra: {
        "runAfter": ra,
        "type": "SetVariable",
        "inputs": {"name": "varItemId", "value": "@outputs('CMP_Item_Id')"},
    })

    # 3. 処理済みの確認(二重処理の防止)
    add("GET_Processed", lambda ra: sp(
        "GetItems",
        {
            "dataset": site_url,
            "table": log_list_id,
            "$filter": "%s eq 'ECS-@{variables('varItemId')}' and %s eq 'Done'"
            % (log_cols["Title"], log_cols["ProcessingStatus"]),
            "$top": 1,
        },
        ra,
    ))
    add("CHK_Not_Processed", lambda ra: {
        "runAfter": ra,
        "type": "If",
        "expression": {"equals": ["@length(body('GET_Processed')?['value'])", 0]},
        "actions": {},
        "else": {"actions": {
            "NTF_Already_Done": teams_card(
                notice_card("すでに処理済みのため、スキップしました", "Skipped",
                            lit("このリクエストは、すでに押印して添付を差し替え済みです。")),
                {},
            ),
            "END_Already_Done": terminate("Succeeded", after("NTF_Already_Done", ALL_STATUSES)),
        }},
    })

    # 4. 証明書の添付を特定する
    add("GET_Attachments", lambda ra: sp_measured(
        "getAttachments",
        {"dataset": site_url, "table": request_list["listId"], "itemId": "@variables('varItemId')"},
        ra,
    ))
    add("FLT_Cert", lambda ra: {
        "runAfter": ra,
        "type": "Query",
        "inputs": {
            "from": expr["attachmentList"],
            "where": "@endsWith(toLower(string(item()?['%s'])), %s)"
            % (attach_fields["name"], lit(cfg["attachment"]["certificateSuffix"].lower())),
        },
    })
    add("CHK_Cert_Single", lambda ra: {
        "runAfter": ra,
        "type": "If",
        "expression": {"equals": ["@length(body('FLT_Cert'))", 1]},
        "actions": {},
        "else": {"actions": stop_branch(
            "Cert_Problem", "該非判定証明書の添付が、1つに特定できません",
            "'CertNotUnique'", "'CertNotUnique'",
            "concat('「%s」で終わる添付が ', string(length(body('FLT_Cert'))), ' 件あります(1件である必要があります)。')"
            % cfg["attachment"]["certificateSuffix"].replace("'", "''"),
            {},
        )},
    })
    add("CMP_Attachment_Id", lambda ra: compose(
        "@first(body('FLT_Cert'))?['%s']" % attach_fields["id"], ra))
    add("CMP_Attachment_Name", lambda ra: compose(
        "@first(body('FLT_Cert'))?['%s']" % attach_fields["name"], ra))

    # 5. 取得 → 作業ライブラリへ複製(元の添付は、この時点では一切変更しない)
    add("GET_Attachment_Content", lambda ra: sp_measured(
        "getAttachmentContent",
        {"dataset": site_url, "table": request_list["listId"],
         "itemId": "@variables('varItemId')", "attachmentId": "@outputs('CMP_Attachment_Id')"},
        ra,
    ))
    add("CMP_Run_Stamp", lambda ra: compose("@formatDateTime(utcNow(), 'yyyyMMdd-HHmmss')", ra))
    add("CMP_Backup_Name", lambda ra: compose(
        "@concat('ECS_', string(variables('varItemId')), '_', outputs('CMP_Run_Stamp'), '_orig_', %s)"
        % attachment_name, ra))
    add("CMP_Work_Name", lambda ra: compose(
        "@concat('ECS_', string(variables('varItemId')), '_', outputs('CMP_Run_Stamp'), '_', %s)"
        % attachment_name, ra))
    add("CREATE_Backup_File", lambda ra: sp_measured(
        "createFile",
        {"dataset": site_url, "folderPath": cfg["libraries"]["workFolderPath"],
         "name": "@outputs('CMP_Backup_Name')", "body": expr["attachmentContent"]},
        ra,
    ))
    add("CREATE_Work_File", lambda ra: sp_measured(
        "createFile",
        {"dataset": site_url, "folderPath": cfg["libraries"]["workFolderPath"],
         "name": "@outputs('CMP_Work_Name')", "body": expr["attachmentContent"]},
        ra,
    ))
    add("CMP_Work_File_Url", lambda ra: compose(
        "@concat(%s, %s, '/', uriComponent(outputs('CMP_Work_Name')))"
        % (lit(site_origin), lit(cfg["libraries"]["workFolderPath"].rstrip("/"))), ra))

    # 6. 印影の画像を取得し、Office Script で押印する(作業コピーに対して)
    add("GET_Stamp_Image", lambda ra: sp_measured(
        "getFileContentByPath",
        {"dataset": site_url, "path": cfg["stampImagePath"]},
        ra,
    ))
    run_cfg = measured["runScript"]
    add("RUN_Script", lambda ra: conn_action(
        EXCEL_API, "shared_excelonlinebusiness", run_cfg["operationId"],
        mapped(run_cfg, {
            "source": run_cfg["source"],
            "drive": run_cfg["drive"],
            "file": expr["createdFileId"],
            "script": run_cfg["scriptReference"],
            "stampBase64": expr["stampBase64"],
            "sheetName": script["sheetName"],
            "anchorCell": script["anchorCell"],
            "approverName": script["approverName"],
            "shapeName": script["shapeName"],
            "targetWidthPt": script.get("targetWidthPt", 0),
            "targetHeightPt": script.get("targetHeightPt", 0),
            "offsetXPt": script.get("offsetXPt", 0),
            "offsetYPt": script.get("offsetYPt", 0),
        }),
        ra, auth,
    ))
    # 戻り値はJSON文字列。string() を通すと、文字列でもオブジェクトでも同じに読める。
    add("CMP_Script_Result", lambda ra: compose(
        "@json(string(%s))" % strip_at(expr["scriptResult"]), ra))
    add("CHK_Script_Stamped", lambda ra: {
        "runAfter": ra,
        "type": "If",
        "expression": {"equals": ["@outputs('CMP_Script_Result')?['status']", "stamped"]},
        "actions": {},
        "else": {"actions": stop_branch(
            "Script_Stop", "押印を中止しました(添付は変更していません)",
            "coalesce(outputs('CMP_Script_Result')?['status'], 'unknown')",
            "coalesce(outputs('CMP_Script_Result')?['status'], 'unknown')",
            "coalesce(outputs('CMP_Script_Result')?['reason'], '(理由なし)')",
            {},
        )},
    })

    # 7. 本番モードのときだけ、添付を差し替える(元のファイルは _orig に残してある)
    if not dry_run:
        add("GET_Stamped_Content", lambda ra: sp_measured(
            "getFileContent",
            {"dataset": site_url, "id": expr["createdFileId"]},
            ra,
        ))
        add("DEL_Attachment", lambda ra: sp_measured(
            "deleteAttachment",
            {"dataset": site_url, "table": request_list["listId"],
             "itemId": "@variables('varItemId')", "attachmentId": "@outputs('CMP_Attachment_Id')"},
            ra,
        ))
        add("ADD_Attachment", lambda ra: sp_measured(
            "addAttachment",
            {"dataset": site_url, "table": request_list["listId"],
             "itemId": "@variables('varItemId')", "name": "@outputs('CMP_Attachment_Name')",
             "body": expr["stampedContent"]},
            ra,
        ))

    # 8. 記録と通知
    placement = (
        "@{outputs('CMP_Script_Result')?['left']}, @{outputs('CMP_Script_Result')?['top']}"
        " (幅 @{outputs('CMP_Script_Result')?['width']} × 高さ @{outputs('CMP_Script_Result')?['height']})"
    )
    add("LOG_Done", lambda ra: log_item(
        "@concat('ECS-', string(variables('varItemId')))",
        "DryRunDone" if dry_run else "Done",
        "OK",
        clip255("concat('left=', string(outputs('CMP_Script_Result')?['left']), ' top=', "
                "string(outputs('CMP_Script_Result')?['top']), ' work=', outputs('CMP_Work_Name'))"),
        ra,
    ))
    guidance = (
        "作業ファイルを開いて、印影の位置・大きさを目視で確認してください。添付ファイルは"
        "まだ差し替えていません。問題なければ、dryRun を false にして本番へ切り替えます。"
        "承認ボタンは、これまでどおり越智さんが押します。"
        if dry_run else
        "添付ファイルを押印済みのものに差し替えました。元のファイルは作業ライブラリの"
        "「_orig」付きのファイルに残っています。内容を目視で確認してから、メールの"
        "「承認」を押してください。"
    )
    done_card = load_card(cards_dir, "stamp_done_card.json", {
        "Heading": "押印しました(DRY-RUN)" if dry_run else "押印して添付を差し替えました",
        "Mode": mode_label,
        "ItemId": item_id,
        "AttachmentName": "@{%s}" % safe_text(attachment_name),
        "Placement": placement,
        "Guidance": guidance,
        "ItemUrl": item_url,
        "WorkFileUrl": "@{outputs('CMP_Work_File_Url')}",
        "RunUrl": run_url,
    })
    add("NTF_Done", lambda ra: teams_card(done_card, ra))

    # SCOPE_Catch: 失敗したアクション名とメッセージを取り出して、記録・通知してから失敗で終える
    failed = "first(body('FLT_Failed_Actions'))"
    error_detail_hint = (
        "元の添付ファイルは、差し替え前の失敗なら無傷です。差し替え中の失敗なら、作業ライブラリの"
        "「_orig」付きのファイルが元のファイルです。"
        if not dry_run else
        "DRY-RUN のため、添付ファイルは変更していません。"
    )
    catch_actions = {
        "FLT_Failed_Actions": {
            "runAfter": {},
            "type": "Query",
            "inputs": {"from": "@result('SCOPE_Main')",
                       "where": "@equals(item()?['status'], 'Failed')"},
        },
        "CMP_Error_Code": compose(
            "@coalesce(%s?['error']?['code'], 'UNKNOWN')" % failed,
            after("FLT_Failed_Actions")),
        "CMP_Error_Raw": compose(
            "@concat('action=', coalesce(%s?['name'], 'unknown'), ' / ', "
            "coalesce(%s?['error']?['message'], '(no message)'))" % (failed, failed),
            after("CMP_Error_Code")),
        "LOG_Error": log_item(
            "@concat('ECS-ERR-', string(variables('varItemId')), '-', "
            "formatDateTime(utcNow(), 'yyyyMMdd-HHmmss'))",
            "Error",
            "@outputs('CMP_Error_Code')",
            clip255("outputs('CMP_Error_Raw')"),
            after("CMP_Error_Raw"),
        ),
        "NTF_Error": teams_card(
            load_card(cards_dir, "stamp_notice_card.json", {
                "Heading": "押印処理が失敗しました",
                "Mode": mode_label,
                "ItemId": item_id,
                "Status": "Error",
                "Detail": "@{%s} %s" % (safe_text("outputs('CMP_Error_Raw')"), error_detail_hint),
                "ItemUrl": item_url,
                "RunUrl": run_url,
            }),
            after("LOG_Error", ALL_STATUSES),
        ),
        # この Terminate が無いと「Catch が成功した」ことで実行全体が成功扱いになり、
        # 本物の失敗が実行履歴で緑色になる
        "END_Failed": terminate(
            "Failed", after("NTF_Error", ALL_STATUSES), "FLOW-500",
            "@{outputs('CMP_Error_Raw')}"),
    }

    mt = measured["mailTrigger"]
    trigger = {
        "type": mt["type"],
        "inputs": {
            "host": {
                "connectionName": "shared_office365",
                "operationId": mt["operationId"],
                "apiId": OUTLOOK_API,
            },
            "parameters": {
                mt["params"]["folderPath"]: cfg["mail"]["folderPath"],
                mt["params"]["from"]: cfg["mail"]["senderAddress"],
                mt["params"]["subjectFilter"]: cfg["mail"]["subjectPrefix"],
            },
            "authentication": auth,
        },
    }

    definition = {
        "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {
            "$connections": {"defaultValue": {}, "type": "Object"},
            "$authentication": {"defaultValue": {}, "type": "SecureObject"},
        },
        "triggers": {"TRG_On_Approval_Mail": trigger},
        "actions": {
            # 変数の初期化は最上位にしか置けないため、スコープの外に残す
            "INIT_varItemId": {
                "runAfter": {},
                "type": "InitializeVariable",
                "inputs": {"variables": [{"name": "varItemId", "type": "integer", "value": 0}]},
            },
            "SCOPE_Main": {
                "runAfter": after("INIT_varItemId"),
                "type": "Scope",
                "actions": main,
            },
            "SCOPE_Catch": {
                "runAfter": {"SCOPE_Main": ["Failed", "TimedOut"]},
                "type": "Scope",
                "actions": catch_actions,
            },
        },
    }

    # メールをきっかけに自動で動くフローは、Request トリガーではないため invoker 接続を
    # 使えない(InvokerConnectionNotAllowed。安否確認ツールで実機判明)。tenant を使う。
    def conn_ref(key, api_name):
        return {
            "runtimeSource": "tenant",
            "connection": {"connectionReferenceLogicalName": cfg["connectionReferences"][key]},
            "api": {"name": api_name},
        }

    return {
        "properties": {
            "connectionReferences": {
                "shared_office365": conn_ref("outlook", "shared_office365"),
                "shared_sharepointonline": conn_ref("sharepoint", "shared_sharepointonline"),
                "shared_excelonlinebusiness": conn_ref("excel", "shared_excelonlinebusiness"),
                "shared_teams": conn_ref("teams", "shared_teams"),
            },
            "definition": definition,
            "templateName": None,
        },
        "schemaVersion": "1.0.0.0",
    }


# ---- Solution の書き出し(実測済みの形式。安否確認ツールと同じ) -------------------

WORKFLOW_METADATA_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<Workflow WorkflowId="{{{guid_lower}}}" Name="{name}" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <JsonFileName>/Workflows/{name}-{guid_upper}.json</JsonFileName>
  <Type>1</Type>
  <Subprocess>0</Subprocess>
  <Category>5</Category>
  <Mode>0</Mode>
  <Scope>4</Scope>
  <OnDemand>0</OnDemand>
  <TriggerOnCreate>0</TriggerOnCreate>
  <TriggerOnDelete>0</TriggerOnDelete>
  <AsyncAutodelete>0</AsyncAutodelete>
  <SyncWorkflowLogOnFailure>0</SyncWorkflowLogOnFailure>
  <StateCode>1</StateCode>
  <StatusCode>2</StatusCode>
  <RunAs>1</RunAs>
  <IsTransacted>1</IsTransacted>
  <IntroducedVersion>1.0</IntroducedVersion>
  <IsCustomizable>1</IsCustomizable>
  <BusinessProcessType>0</BusinessProcessType>
  <IsCustomProcessingStepAllowedForOtherPublishers>1</IsCustomProcessingStepAllowedForOtherPublishers>
  <ModernFlowType>0</ModernFlowType>
  <PrimaryEntity>none</PrimaryEntity>
  <LocalizedNames>
    <LocalizedName languagecode="1033" description="{name}" />
  </LocalizedNames>
</Workflow>
"""

CUSTOMIZATIONS_XML = """<?xml version="1.0" encoding="utf-8"?>
<ImportExportXml xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Entities />
  <Roles />
  <Workflows />
  <FieldSecurityProfiles />
  <Templates />
  <EntityMaps />
  <EntityRelationships />
  <OrganizationSettings />
  <optionsets />
  <CustomControls />
  <SolutionPluginAssemblies />
  <EntityDataProviders />
  <Languages>
    <Language>1033</Language>
  </Languages>
</ImportExportXml>
"""

SOLUTION_XML_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<ImportExportXml version="9.1.0.643" SolutionPackageVersion="9.1" languagecode="1033" generatedBy="CrmLive" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <SolutionManifest>
    <UniqueName>{solution_name}</UniqueName>
    <LocalizedNames>
      <LocalizedName description="{solution_name}" languagecode="1033" />
    </LocalizedNames>
    <Descriptions />
    <Version>1.0</Version>
    <Managed>2</Managed>
    <Publisher>
      <UniqueName>{publisher_name}</UniqueName>
      <LocalizedNames>
        <LocalizedName description="{publisher_name}" languagecode="1033" />
      </LocalizedNames>
      <Descriptions>
        <Description description="{publisher_name}" languagecode="1033" />
      </Descriptions>
      <EMailAddress xsi:nil="true"></EMailAddress>
      <SupportingWebsiteUrl xsi:nil="true"></SupportingWebsiteUrl>
      <CustomizationPrefix>{publisher_prefix}</CustomizationPrefix>
      <CustomizationOptionValuePrefix>50017</CustomizationOptionValuePrefix>
      <Addresses>
        <Address>
          <AddressNumber>1</AddressNumber>
          <AddressTypeCode>1</AddressTypeCode>
          <ShippingMethodCode>1</ShippingMethodCode>
        </Address>
        <Address>
          <AddressNumber>2</AddressNumber>
          <AddressTypeCode>1</AddressTypeCode>
          <ShippingMethodCode>1</ShippingMethodCode>
        </Address>
      </Addresses>
    </Publisher>
    <RootComponents>
{root_components}
    </RootComponents>
    <MissingDependencies />
  </SolutionManifest>
</ImportExportXml>
"""


def write_solution(out_dir, cfg, flows):
    workflows_dir = os.path.join(out_dir, "Workflows")
    other_dir = os.path.join(out_dir, "Other")
    os.makedirs(workflows_dir, exist_ok=True)
    os.makedirs(other_dir, exist_ok=True)

    root_components = []
    for name, (guid, flow_json) in flows.items():
        base = "%s-%s" % (name, guid.upper())
        with open(os.path.join(workflows_dir, base + ".json"), "w", encoding="utf-8") as fh:
            json.dump(flow_json, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        with open(os.path.join(workflows_dir, base + ".json.data.xml"), "w", encoding="utf-8") as fh:
            fh.write(WORKFLOW_METADATA_TEMPLATE.format(
                guid_lower=guid.lower(), guid_upper=guid.upper(), name=name))
        root_components.append(
            '      <RootComponent type="29" id="{%s}" behavior="0" />' % guid.lower())

    with open(os.path.join(other_dir, "Customizations.xml"), "w", encoding="utf-8") as fh:
        fh.write(CUSTOMIZATIONS_XML)
    solution_cfg = cfg["solution"]
    with open(os.path.join(other_dir, "Solution.xml"), "w", encoding="utf-8") as fh:
        fh.write(SOLUTION_XML_TEMPLATE.format(
            solution_name=solution_cfg["uniqueName"],
            publisher_name=solution_cfg["publisherUniqueName"],
            publisher_prefix=solution_cfg["publisherPrefix"],
            root_components="\n".join(root_components)))
    with open(os.path.join(other_dir, "Relationships.xml"), "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n<Relationships />\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="../deploy_config.json", help="実値の設定ファイル")
    parser.add_argument("--out", default="./src", help="Solutionソースの出力先")
    parser.add_argument("--cards", default="../cards", help="Adaptive Card(JSON)のあるフォルダ")
    args = parser.parse_args()

    if not os.path.exists(args.config):
        sys.exit("設定ファイルが見つかりません: %s\n"
                 "deploy_config.example.json をコピーして実値を入れてください。" % args.config)
    with open(args.config, encoding="utf-8-sig") as fh:
        cfg = json.load(fh)

    problems = check_config(cfg)
    if problems:
        print("設定に、未実測・不正な値があります。生成を中止します(推測値では作りません)。")
        print("")
        for line in problems:
            print("  - " + line)
        print("")
        print("実測の手順: docs/MEASUREMENT_GUIDE.md")
        sys.exit(1)

    # 生成の前に、いま添付を差し替える設定かどうかを必ず表示する。
    # 本番モードへ切り替わったことに気づかないまま取り込むのが、一番危ない。
    if cfg.get("dryRun", True):
        print("[DRY-RUN] 添付ファイルは差し替えません。作業ライブラリ上のコピーにだけ押印します。")
    else:
        print("*" * 70)
        print("[本番モード] dryRun=false です。")
        print("  押印のあと、リクエストの添付ファイルを押印済みのものへ差し替えます。")
        print("  元のファイルは作業ライブラリの「_orig」付きファイルに残ります。")
        print("*" * 70)
    print("")

    flows = {FLOW_NAME: (cfg["workflowIds"][FLOW_NAME], build_flow(cfg, args.cards))}
    write_solution(args.out, cfg, flows)

    print("生成しました: %s" % os.path.abspath(args.out))
    print("  - %s" % FLOW_NAME)
    print("")
    print("次のコマンドでインポートしてください:")
    print("  pac solution pack --zipfile ./ExportControlStamper.zip --folder %s" % args.out)
    print("  pac solution import --path ./ExportControlStamper.zip")


if __name__ == "__main__":
    main()
