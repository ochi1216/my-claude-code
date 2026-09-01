#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Power Automate クラウドフローの定義(JSON)とSolutionソースツリーを生成する。

GUIでの手組みを避け、`pac solution pack` / `pac solution import` で
DEV環境へ流し込めるファイル一式を出力する。

出力される構造(Dataverseの実物からリバースエンジニアリングした形式):

    <out>/
      Other/Solution.xml          … RootComponents に type="29" でフローを登録
      Other/Customizations.xml    … <Workflows /> は空のまま(ここには書かない)
      Workflows/
        <Name>-<GUID大文字>.json           … フロー定義(clientdata相当)
        <Name>-<GUID大文字>.json.data.xml  … ワークフローのメタデータ

使い方:

    python build_flows_20260901_02.py --config deploy_config.json --out ./src
    pac solution pack --zipfile ./EQSafetyCheckin.zip --folder ./src
    pac solution import --environment <ENV_ID> --path ./EQSafetyCheckin.zip

コネクタの operationId / パラメータ名は、実テナントからエクスポートした
フローの実測値に基づく(docs/GATE_STATUS.md の Gate B/D 参照)。

20260901_02 で追加した機能(deploy_config.json の features で個別に有効化する):

    features.errorLogging
        EQ06・EQ05 の本体を SCOPE_Try で包み、失敗したら SCOPE_Catch から
        EQ_Received_Items へ1行(ProcessingStatus=Error)記録して失敗終了する。
        EQ_Received_Items のリストIDと列内部名の実測値が必要。

    features.eventClose
        全員分の回答待ちが終わったら EQ_Events の AlertStatus を Closed にする。
        失敗して SCOPE_Catch に入った場合は Error にする。どちらも Open ではなく
        なるため、EQ05 が終わった訓練の集計を投稿し続けることがなくなる。
        SharePoint「項目の更新」アクションの operationId とパラメータ名の
        実測値が必要。

どちらも未指定なら false で、出力は 20260901_01 と同一になる。
"""

import argparse
import json
import os
import re
import sys

# --- 実測済みのコネクタ定義(evidence/connector_schema.md 参照) --------------

SP_API_ID = "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
TEAMS_API_ID = "/providers/Microsoft.PowerApps/apis/shared_teams"

# すべてのコネクタアクションで共通の認証ブロック
AUTH_BLOCK = {
    "type": "Raw",
    "value": "@json(decodeBase64(triggerOutputs().headers['X-MS-APIM-Tokens']))['$ConnectionKey']",
}

# 震度コード → 内部数値。5弱=50, 5強=55 のように、5弱と5強を数値で区別できるようにしている
INTENSITY_VALUES = [
    ("1", 10),
    ("2", 20),
    ("3", 30),
    ("4", 40),
    ("5-", 50),
    ("5+", 55),
    ("6-", 60),
    ("6+", 65),
    ("7", 70),
]


def sp_action(operation_id, parameters, run_after):
    """SharePointコネクタのアクションを1つ組み立てる。"""
    return {
        "runAfter": run_after,
        "type": "OpenApiConnection",
        "inputs": {
            "host": {
                "connectionName": "shared_sharepointonline",
                "operationId": operation_id,
                "apiId": SP_API_ID,
            },
            "parameters": parameters,
            "authentication": AUTH_BLOCK,
        },
    }


def teams_post_card(parameters, run_after):
    """Teams「チャットやチャネルにカードを投稿する」(応答を待たない版)。"""
    return {
        "runAfter": run_after,
        "type": "OpenApiConnection",
        "inputs": {
            "host": {
                "connectionName": "shared_teams",
                "operationId": "PostCardToConversation",
                "apiId": TEAMS_API_ID,
            },
            "parameters": parameters,
            "authentication": AUTH_BLOCK,
        },
    }


def teams_post_card_and_wait(parameters, run_after, timeout):
    """Teams「アダプティブ カードを投稿して応答を待機する」。

    このテナントのTeamsコネクタには「カードに応答があったとき」トリガーが無く
    (存在するのは絵文字リアクション用の WebhookMessageReactionTrigger のみ)、
    投げ切り+応答トリガーの非同期設計が成立しないため、この待機型を使う。
    18名分を待つ間フローが居座らないよう、呼び出し側でループを並列化し、
    ここでタイムアウトを設定する。
    """
    return {
        "runAfter": run_after,
        "type": "OpenApiConnectionWebhook",
        "inputs": {
            "host": {
                "connectionName": "shared_teams",
                "operationId": "PostCardAndWaitForResponse",
                "apiId": TEAMS_API_ID,
            },
            "parameters": parameters,
            "authentication": AUTH_BLOCK,
        },
        "limit": {"timeout": timeout},
    }


def terminate(status, code=None, message=None):
    """フローを終了するアクション。閾値未満のような正常終了にも使う。"""
    inputs = {"runStatus": status}
    if status == "Failed":
        inputs["runError"] = {"code": code or "", "message": message or ""}
    return {"runAfter": {}, "type": "Terminate", "inputs": inputs}


def scope(actions, run_after):
    """複数のアクションを1つのスコープにまとめる。"""
    return {"runAfter": run_after, "type": "Scope", "actions": actions}


def is_measured(value):
    """設定値が実測値で埋まっているかどうか。

    deploy_config.example.json のプレースホルダは <...> の形で書いてあるため、
    それが残っている値・空文字は「未実測」として扱う。推測値でフローを生成すると
    インポートは通ってしまい、実行時に初めて失敗するため原因が分かりにくい。
    """
    return isinstance(value, str) and value.strip() != "" and "<" not in value


def read_features(cfg):
    """機能フラグを読む。未指定は全てオフ(=20260901_01と同じ出力になる)。"""
    features = cfg.get("features", {})
    return {
        "errorLogging": bool(features.get("errorLogging", False)),
        "eventClose": bool(features.get("eventClose", False)),
    }


def require_error_log_config(cfg):
    """エラー処理に必要な実測値が揃っているか確認し、リストIDと列内部名を返す。"""
    list_id = cfg.get("listIds", {}).get("EQ_Received_Items", "")
    if not is_measured(list_id):
        raise SystemExit(
            "features.errorLogging を有効にするには listIds.EQ_Received_Items が必要です。\n"
            "取得方法は solution/README.md を参照してください。"
        )
    columns = cfg.get("columnInternalNames", {}).get("EQ_Received_Items", {})
    # CreatedAt は必須にしない。実測したリストにこの列は無く、SharePointの標準列
    # Created(作成日時)が自動で入るため、無くても発生時刻は失われない。
    missing = [
        name
        for name in ("Title", "ProcessingStatus", "ErrorCode", "ErrorDetail")
        if not is_measured(columns.get(name, ""))
    ]
    if missing:
        raise SystemExit(
            "EQ_Received_Items の列内部名が未実測です: %s\n"
            "solution/README.md「列内部名の実測手順」に従って実測し、deploy_config.json の\n"
            "columnInternalNames.EQ_Received_Items へ入れてください。" % ", ".join(missing)
        )
    return list_id, columns


def require_update_action(cfg):
    """SharePoint「項目の更新」アクションの実測値を確認して返す。

    operationId もパラメータ名も、公開情報からは確定できない。推測で書くと
    実行時に 404 / BadRequest になるため、実測値が入るまでは生成させない。
    """
    upd = cfg.get("sharePointUpdateAction", {})
    if not (
        is_measured(upd.get("operationId", "")) and is_measured(upd.get("idParameter", ""))
    ):
        raise SystemExit(
            "features.eventClose を有効にするには sharePointUpdateAction の\n"
            "operationId と idParameter の実測値が必要です(推測すると実行時に失敗します)。\n"
            "実測手順は solution/README.md「SharePoint『項目の更新』アクションの実測手順」を参照。"
        )
    return upd


def build_close_action(cfg, upd, alert_status, run_after):
    """EQ_Events の AlertStatus を書き換えるアクションを1つ組み立てる。

    対象はイベントのタイトルではなく SharePoint の項目ID(整数)で指す。
    Title は必須列のため、更新でも同じ値を送り直しておく。
    """
    columns = cfg["columnInternalNames"]["EQ_Events"]
    return sp_action(
        upd["operationId"],
        {
            "dataset": cfg["sharePointSiteUrl"],
            "table": cfg["listIds"]["EQ_Events"],
            upd["idParameter"]: "@variables('varEventItemId')",
            "item/%s" % columns["Title"]: "@variables('varEventID')",
            "item/%s" % columns["AlertStatus"]: alert_status,
        },
        run_after,
    )


def build_catch_actions(cfg, log_list_id, log_columns, title_expr, close_action=None):
    """SCOPE_Catch の中身を組み立てる。

    SCOPE_Try が Failed / TimedOut で終わったときだけ動き、EQ_Received_Items へ
    1行記録してから、実行そのものは失敗として終わらせる。最後の Terminate が無いと
    「Catchが成功した」ことで実行全体が成功扱いになり、本物の失敗が実行履歴で
    緑色になってしまう。
    """
    failed = "first(body('FLT_Failed_Actions'))"

    log_parameters = {
        "dataset": cfg["sharePointSiteUrl"],
        "table": log_list_id,
        "item/%s" % log_columns["Title"]: title_expr,
        "item/%s" % log_columns["ProcessingStatus"]: "Error",
        "item/%s" % log_columns["ErrorCode"]: "@outputs('CMP_Error_Code')",
        "item/%s" % log_columns["ErrorDetail"]: "@outputs('CMP_Error_Message')",
    }
    # 発生時刻を入れる列があれば書く。無ければSharePointの標準列 Created に任せる。
    created_at = log_columns.get("CreatedAt", "")
    if is_measured(created_at):
        log_parameters["item/%s" % created_at] = "@utcNow()"

    actions = {
        # result() はスコープ直下のアクションの結果を配列で返す。式には filter 関数が
        # 無いため、「配列のフィルター」で失敗したものだけを残してから先頭を見る。
        "FLT_Failed_Actions": {
            "runAfter": {},
            "type": "Query",
            "inputs": {
                "from": "@result('SCOPE_Try')",
                "where": "@equals(item()?['status'], 'Failed')",
            },
        },
        "CMP_Error_Code": {
            "runAfter": {"FLT_Failed_Actions": ["Succeeded"]},
            "type": "Compose",
            "inputs": "@coalesce(%s?['error']?['code'], 'UNKNOWN')" % failed,
        },
        "CMP_Error_Raw": {
            "runAfter": {"CMP_Error_Code": ["Succeeded"]},
            "type": "Compose",
            "inputs": (
                "@concat('action=', coalesce(%s?['name'], 'unknown'), ' / ', "
                "coalesce(%s?['error']?['message'], '(no message)'))" % (failed, failed)
            ),
        },
        # 1行テキスト列の上限は255文字。超えたまま書き込むと記録そのものが失敗する
        "CMP_Error_Message": {
            "runAfter": {"CMP_Error_Raw": ["Succeeded"]},
            "type": "Compose",
            "inputs": (
                "@if(greater(length(outputs('CMP_Error_Raw')), 255), "
                "concat(substring(outputs('CMP_Error_Raw'), 0, 252), '...'), "
                "outputs('CMP_Error_Raw'))"
            ),
        },
        "SP_Log_Error": sp_action("PostItem", log_parameters, {"CMP_Error_Message": ["Succeeded"]}),
    }

    last = "SP_Log_Error"
    if close_action is not None:
        # 失敗した回のイベントを Open のまま残すと、EQ05 が15分ごとに、終わった訓練の
        # 集計カードをチャネルへ投稿し続ける。Closed ではなく Error にして、あとから
        # 「失敗して終わった回」だと分かるようにする。
        actions["CHK_Event_Created"] = {
            "runAfter": {"SP_Log_Error": ["Succeeded"]},
            "type": "If",
            "expression": {"and": [{"greater": ["@variables('varEventItemId')", 0]}]},
            "actions": {"SP_Mark_Event_Error": close_action},
            "else": {"actions": {}},
        }
        last = "CHK_Event_Created"

    # 記録側が失敗しても、実行は失敗として終わらせる
    actions["END_Failed"] = {
        "runAfter": {last: ["Succeeded", "Failed", "Skipped", "TimedOut"]},
        "type": "Terminate",
        "inputs": {
            "runStatus": "Failed",
            "runError": {
                "code": "FLOW-500",
                "message": "@{outputs('CMP_Error_Message')}",
            },
        },
    }
    return actions


def load_card(cards_dir, filename, bindings):
    """Adaptive Cardを読み込み、${Placeholder} をフローの式へ置換して文字列で返す。

    Power Automateはカード内のテンプレート構文(${...})を解決しないため、
    投稿前にフロー側の式 @{...} へ差し替えておく必要がある。
    """
    path = os.path.join(cards_dir, filename)
    with open(path, encoding="utf-8-sig") as fh:
        card_text = fh.read()

    def replace(match):
        key = match.group(1)
        if key not in bindings:
            raise KeyError(
                "カード %s のプレースホルダ ${%s} に対応する式が未定義です" % (filename, key)
            )
        return bindings[key]

    card_text = re.sub(r"\$\{(\w+)\}", replace, card_text)

    # 1行に畳んでから返す(JSONの値として埋め込むため、整形は不要)
    return json.dumps(json.loads(card_text), ensure_ascii=False)


def build_eq06(cfg, cards_dir):
    """EQ06_Manual_Drill_DEV(手動訓練トリガー)の定義を組み立てる。

    docs/FLOW_LOGIC_SPEC.md のロジックに対応するが、拠点設定と震度値の受け渡しは
    変数(varSiteConfig / varIntensityValue)経由にしている。Switchアクション自体には
    出力が無く、実行された分岐内のアクションしか参照できないため。
    """
    site_url = cfg["sharePointSiteUrl"]
    lists = cfg["listIds"]
    columns = cfg["columnInternalNames"]

    features = read_features(cfg)
    error_logging = features["errorLogging"]
    close_event = features["eventClose"]
    # イベントIDと項目IDは、エラー記録とクローズ処理の両方で使う。どちらも
    # 並列ループの外(1回しか通らない場所)でしか書き換えないため、変数で持ってよい。
    track_event = error_logging or close_event
    update_action = require_update_action(cfg) if close_event else None
    log_list_id, log_columns = (
        require_error_log_config(cfg) if error_logging else (None, None)
    )

    def col(list_name, display_name):
        """表示名から内部名を引く。

        Excelアップロードで作ったリストは内部名が field_1, field_2 ... と
        なるため(evidence/sharepoint_internal_names.json)、フローの
        item/<列> や $filter では必ず内部名を使う。
        """
        try:
            return columns[list_name][display_name]
        except KeyError:
            raise KeyError(
                "%s の列 '%s' の内部名が deploy_config.json に未定義です"
                % (list_name, display_name)
            )

    # --- 1. 拠点設定のSwitch(各ケースで変数へ書き込む) ---
    site_cases = {}
    for site in cfg["sites"]:
        code = site["siteCode"]
        site_cases[code] = {
            "case": code,
            "actions": {
                "SET_Site_%s" % code: {
                    "runAfter": {},
                    "type": "SetVariable",
                    "inputs": {
                        "name": "varSiteConfig",
                        "value": {
                            "SiteName": site["siteName"],
                            "ThresholdValue": site["thresholdValue"],
                            "TeamId": site["teamId"],
                            "ChannelId": site["channelId"],
                        },
                    },
                }
            },
        }

    # --- 2. 震度コード→数値のSwitch ---
    intensity_cases = {}
    for code, value in INTENSITY_VALUES:
        key = "Intensity_%s" % code.replace("-", "minus").replace("+", "plus")
        intensity_cases[code] = {
            "case": code,
            "actions": {
                "SET_%s" % key: {
                    "runAfter": {},
                    "type": "SetVariable",
                    "inputs": {"name": "varIntensityValue", "value": value},
                }
            },
        }

    # --- 3. 閾値を超えたときの本処理 ---
    channel_card = load_card(
        cards_dir,
        "channel_alert_card.json",
        {
            "TestPrefix": "@{if(triggerBody()?['IsTest'], '【訓練】', '')}",
            "SiteName": "@{variables('varSiteConfig')?['SiteName']}",
            "Intensity": "@{triggerBody()?['IntensityCode']}",
            "Epicenter": "@{triggerBody()?['Epicenter']}",
            "OccurredAtJST": "@{outputs('CMP_OccurredAtJST')}",
            "EventID": "@{outputs('CMP_EventID')}",
        },
    )

    checkin_card = load_card(
        cards_dir,
        "checkin_card.json",
        {
            "TestPrefix": "@{if(triggerBody()?['IsTest'], '【訓練】', '')}",
            "EventID": "@{outputs('CMP_EventID')}",
            "SiteName": "@{variables('varSiteConfig')?['SiteName']}",
            "Intensity": "@{triggerBody()?['IntensityCode']}",
            "OccurredAtJST": "@{outputs('CMP_OccurredAtJST')}",
            "EmployeeID": "@{items('LOOP_Each_Member')?['%s']}" % col("EQ_Config_Members", "Title"),
        },
    )

    # IsActive / IsManager はテキスト型で作られているため、数値ではなく文字列で比較する
    flags = cfg.get("memberFlagValues", {"active": "TRUE", "notManager": "FALSE"})
    member_filter = "%s eq '@{triggerBody()?['SiteCode']}' and %s eq '%s' and %s eq '%s'" % (
        col("EQ_Config_Members", "SiteCode"),
        col("EQ_Config_Members", "IsActive"),
        flags["active"],
        col("EQ_Config_Members", "IsManager"),
        flags["notManager"],
    )

    # 検証段階の誤送信防止。testRecipientOverride が空でない限り、
    # 個人カードの宛先は名簿ではなく常にこのアドレスになる。
    #
    # IsTestの状態や選んだ拠点には依存させない。守りたいのは人為ミス
    # (IsTestの付け忘れ、拠点の選び間違い)であり、人の操作を条件にすると
    # そのミス自体で安全弁が外れてしまうため。
    # 本番運用へ移る際は、この設定を空文字にする(それが唯一の切替操作)。
    member_email = "items('LOOP_Each_Member')?['%s']" % col("EQ_Config_Members", "Email")
    override = cfg.get("testRecipientOverride", "").strip()
    recipient_expr = override if override else "@%s" % member_email

    # 回答の受け取り方。このテナントには「カードに応答があったとき」トリガーが
    # 無いため、既定は待機型(wait)。postOnlyにすると投げ切りになり回答は拾わない。
    response_mode = cfg.get("responseMode", "wait")
    loop_concurrency = cfg.get("loopConcurrency", 20)
    response_timeout = cfg.get("responseTimeout", "PT1H")

    if response_mode == "wait":
        # 応答JSONの構造は evidence/teams_card_response_sanitized.json の実測値。
        # data配下がカードの入力値、responder配下が実際に回答した人。
        resp = "body('TM_Post_CheckIn_Card')"
        code = "%s?['data']?['responseCode']" % resp
        # 1=無事/出社可, 2=無事/出社不可, 3=被災/出社可, 4=被災/出社不可。
        # 並列ループ内では変数を使えない(全イテレーションで共有されて値が混ざる)ため、
        # 安否・出社可否は式で直接計算する。
        safety = "if(or(equals(%s,'1'),equals(%s,'2')),'Safe','Affected')" % (code, code)
        work = "if(or(equals(%s,'1'),equals(%s,'3')),'Available','Unavailable')" % (code, code)
        comment = "coalesce(%s?['data']?['comment'],'')" % resp
        employee_name = "items('LOOP_Each_Member')?['%s']" % col(
            "EQ_Config_Members", "DisplayName"
        )

        manager_card = load_card(
            cards_dir,
            "manager_alert_card.json",
            {
                "TestPrefix": "@{if(triggerBody()?['IsTest'], '【訓練】', '')}",
                "EmployeeName": "@{%s}" % employee_name,
                "EmployeeID": "@{%s?['data']?['employeeId']}" % resp,
                "SiteName": "@{variables('varSiteConfig')?['SiteName']}",
                "SafetyStatus": "@{%s}" % safety,
                "WorkStatus": "@{%s}" % work,
                "Comment": "@{%s}" % comment,
                "EventID": "@{outputs('CMP_EventID')}",
            },
        )

        manager_filter = "%s eq '@{triggerBody()?['SiteCode']}' and %s eq '%s' and %s eq '%s'" % (
            col("EQ_Config_Members", "SiteCode"),
            col("EQ_Config_Members", "IsActive"),
            flags["active"],
            col("EQ_Config_Members", "IsManager"),
            flags.get("isManager", "TRUE"),
        )
        manager_email = "items('LOOP_Notify_Managers')?['%s']" % col(
            "EQ_Config_Members", "Email"
        )
        manager_recipient = override if override else "@%s" % manager_email

        # 回答あり/未回答の分岐は、待機アクションの後続を「1つ」にまとめる。
        # 後続を2つに分けて片方をスキップさせると、タイムアウト時に
        # 「ActionFailed. No dependent actions succeeded」でループ全体が失敗する。
        loop_actions = {
            "TM_Post_CheckIn_Card": teams_post_card_and_wait(
                {
                    "poster": "Flow bot",
                    "location": "Chat with Flow bot",
                    # 待機型では recipient がオブジェクト扱いになるため、
                    # 投げ切り版の body/recipient とは異なり /to まで指定する
                    "body/body/recipient/to": recipient_expr,
                    "body/body/messageBody": checkin_card,
                    "body/body/updateMessage": "回答を受け付けました。ありがとうございます。",
                },
                {},
                response_timeout,
            ),
            "CHK_Responded": {
                # TimedOut(時間内に回答が無かった)は異常ではないので受ける。
                # Failedは受けない。本物の失敗はそのまま表に出したいため。
                "runAfter": {"TM_Post_CheckIn_Card": ["Succeeded", "TimedOut"]},
                "type": "If",
                "expression": {
                    "and": [
                        {
                            "equals": [
                                "@actions('TM_Post_CheckIn_Card')?['status']",
                                "Succeeded",
                            ]
                        }
                    ]
                },
                "actions": {
                    "SP_Create_Response": sp_action(
                        "PostItem",
                        {
                            "dataset": site_url,
                            "table": lists["EQ_Responses"],
                            # EventIDと社員IDの組をキーにしておくと、後から集計・突合しやすい
                            "item/%s" % col("EQ_Responses", "Title"): (
                                "@concat(%s?['data']?['eventId'],'|',%s?['data']?['employeeId'])"
                                % (resp, resp)
                            ),
                            "item/%s" % col("EQ_Responses", "EventID"): (
                                "@%s?['data']?['eventId']" % resp
                            ),
                            "item/%s" % col("EQ_Responses", "EmployeeID"): (
                                "@%s?['data']?['employeeId']" % resp
                            ),
                            # カード内のIDではなく、実際に回答した人のメールを記録する
                            # (カードのdataは詐称されうるため。応答にはresponderが必ず入る)
                            "item/%s" % col("EQ_Responses", "Email"): (
                                "@%s?['responder']?['email']" % resp
                            ),
                            # 列が数値型のため、文字列で返る responseCode を変換する
                            "item/%s" % col("EQ_Responses", "ResponseCode"): "@int(%s)" % code,
                            "item/%s" % col("EQ_Responses", "SafetyStatus"): "@%s" % safety,
                            "item/%s" % col("EQ_Responses", "WorkStatus"): "@%s" % work,
                            "item/%s" % col("EQ_Responses", "RespondedAt"): (
                                "@%s?['responseTime']" % resp
                            ),
                            # 空欄のInput.Textは応答に現れないため、既定値を用意する
                            "item/%s" % col("EQ_Responses", "Comment"): "@%s" % comment,
                            "item/%s" % col("EQ_Responses", "Revision"): 1,
                        },
                        {},
                    ),
                    "CHK_Affected": {
                        "runAfter": {"SP_Create_Response": ["Succeeded"]},
                        "type": "If",
                        "expression": {"and": [{"equals": ["@%s" % safety, "Affected"]}]},
                        "actions": {
                            "GET_Managers": sp_action(
                                "GetItems",
                                {
                                    "dataset": site_url,
                                    "table": lists["EQ_Config_Members"],
                                    "$filter": manager_filter,
                                    "$orderby": "%s asc"
                                    % col("EQ_Config_Members", "EscalationOrder"),
                                    "$top": 50,
                                },
                                {},
                            ),
                            "LOOP_Notify_Managers": {
                                "runAfter": {"GET_Managers": ["Succeeded"]},
                                "type": "Foreach",
                                "foreach": "@body('GET_Managers')?['value']",
                                "actions": {
                                    "TM_Notify_Manager": teams_post_card(
                                        {
                                            "poster": "Flow bot",
                                            "location": "Chat with Flow bot",
                                            "body/recipient": manager_recipient,
                                            "body/messageBody": manager_card,
                                        },
                                        {},
                                    )
                                },
                            },
                        },
                        "else": {"actions": {}},
                    },
                },
                "else": {
                    "actions": {
                        # 未回答も訓練の結果のひとつ。記録だけ残して正常終了させる
                        "CMP_No_Response": {
                            "runAfter": {},
                            "type": "Compose",
                            "inputs": {
                                "result": "no response within timeout",
                                "employeeId": "@items('LOOP_Each_Member')?['%s']"
                                % col("EQ_Config_Members", "Title"),
                                "eventId": "@outputs('CMP_EventID')",
                            },
                        }
                    }
                },
            },
        }
    else:
        loop_actions = {
            "TM_Post_CheckIn_Card": teams_post_card(
                {
                    "poster": "Flow bot",
                    "location": "Chat with Flow bot",
                    "body/recipient": recipient_expr,
                    "body/messageBody": checkin_card,
                },
                {},
            )
        }

    # 機能を有効にすると、イベントIDと項目IDを変数へ控える分だけ鎖が伸びる
    create_event_after = (
        {"SET_varEventID": ["Succeeded"]} if track_event else {"CMP_EventID": ["Succeeded"]}
    )
    occurred_after = (
        {"SET_varEventItemId": ["Succeeded"]}
        if close_event
        else {"SP_Create_Event": ["Succeeded"]}
    )

    threshold_actions = {
        "CMP_EventID": {
            "runAfter": {},
            "type": "Compose",
            "inputs": (
                "@concat('EQ-', formatDateTime(utcNow(), 'yyyyMMdd-HHmmss'), '-', "
                "triggerBody()?['SiteCode'])"
            ),
        },
        "SP_Create_Event": sp_action(
            "PostItem",
            {
                "dataset": site_url,
                "table": lists["EQ_Events"],
                "item/%s" % col("EQ_Events", "Title"): "@outputs('CMP_EventID')",
                "item/%s" % col("EQ_Events", "SiteCode"): "@triggerBody()?['SiteCode']",
                "item/%s" % col("EQ_Events", "OccurredAt"): "@utcNow()",
                "item/%s" % col("EQ_Events", "Epicenter"): "@triggerBody()?['Epicenter']",
                "item/%s" % col("EQ_Events", "SiteIntensityCode"): "@triggerBody()?['IntensityCode']",
                "item/%s" % col("EQ_Events", "SiteIntensityValue"): "@variables('varIntensityValue')",
                "item/%s" % col("EQ_Events", "AlertStatus"): "Open",
                "item/%s" % col("EQ_Events", "StartedBy"): "Manual",
                "item/%s" % col("EQ_Events", "IsTest"): "@triggerBody()?['IsTest']",
            },
            create_event_after,
        ),
        "CMP_OccurredAtJST": {
            "runAfter": occurred_after,
            "type": "Compose",
            "inputs": (
                "@convertTimeZone(utcNow(), 'UTC', 'Tokyo Standard Time', 'yyyy/MM/dd HH:mm')"
            ),
        },
        "TM_Post_Channel_Alert": teams_post_card(
            {
                "poster": "Flow bot",
                "location": "Channel",
                "body/recipient/groupId": "@variables('varSiteConfig')?['TeamId']",
                "body/recipient/channelId": "@variables('varSiteConfig')?['ChannelId']",
                "body/messageBody": channel_card,
            },
            {"CMP_OccurredAtJST": ["Succeeded"]},
        ),
        "GET_Active_Members": sp_action(
            "GetItems",
            {
                "dataset": site_url,
                "table": lists["EQ_Config_Members"],
                "$filter": member_filter,
                "$top": 500,
            },
            {"TM_Post_Channel_Alert": ["Succeeded"]},
        ),
        "CHK_Members_Found": {
            "runAfter": {"GET_Active_Members": ["Succeeded"]},
            "type": "If",
            "expression": {
                "and": [
                    {
                        "equals": [
                            "@length(body('GET_Active_Members')?['value'])",
                            0,
                        ]
                    }
                ]
            },
            "actions": {
                "END_No_Members": terminate(
                    "Failed", "CFG-003", "no active members for this site"
                )
            },
            "else": {
                "actions": {
                    "LOOP_Each_Member": {
                        "runAfter": {},
                        "type": "Foreach",
                        "foreach": "@body('GET_Active_Members')?['value']",
                        # 全員分を同時に待つ。直列にすると1人目の回答まで他の人へ
                        # カードが届かない(レビュー指摘)。上限は50。
                        "runtimeConfiguration": {
                            "concurrency": {"repetitions": loop_concurrency}
                        },
                        "actions": loop_actions,
                    }
                }
            },
        },
    }

    if track_event:
        threshold_actions["SET_varEventID"] = {
            "runAfter": {"CMP_EventID": ["Succeeded"]},
            "type": "SetVariable",
            "inputs": {"name": "varEventID", "value": "@outputs('CMP_EventID')"},
        }
    if close_event:
        threshold_actions["SET_varEventItemId"] = {
            "runAfter": {"SP_Create_Event": ["Succeeded"]},
            "type": "SetVariable",
            # SharePointの更新アクションは、タイトルではなく項目ID(整数)で対象を指す
            "inputs": {"name": "varEventItemId", "value": "@body('SP_Create_Event')?['ID']"},
        }
        # 全員分の回答待ちが終わったらイベントを閉じる。閉じないと EQ05 が
        # 15分ごとに、終わった訓練の集計カードをチャネルへ投稿し続ける。
        threshold_actions["SP_Close_Event"] = build_close_action(
            cfg, update_action, "Closed", {"CHK_Members_Found": ["Succeeded"]}
        )

    # 変数の初期化はフローの最上位にしか置けない(スコープの中に入れるとインポートで
    # 弾かれる)。このため SCOPE_Try で包むのは、初期化より後のアクションだけにする。
    init_actions = {
        "INIT_varSiteConfig": {
            "runAfter": {},
            "type": "InitializeVariable",
            "inputs": {
                "variables": [{"name": "varSiteConfig", "type": "object", "value": {}}]
            },
        },
        "INIT_varIntensityValue": {
            "runAfter": {"INIT_varSiteConfig": ["Succeeded"]},
            "type": "InitializeVariable",
            "inputs": {
                "variables": [{"name": "varIntensityValue", "type": "integer", "value": 0}]
            },
        },
    }
    last_init = "INIT_varIntensityValue"
    if track_event:
        init_actions["INIT_varEventID"] = {
            "runAfter": {last_init: ["Succeeded"]},
            "type": "InitializeVariable",
            "inputs": {"variables": [{"name": "varEventID", "type": "string", "value": ""}]},
        }
        last_init = "INIT_varEventID"
    if close_event:
        init_actions["INIT_varEventItemId"] = {
            "runAfter": {last_init: ["Succeeded"]},
            "type": "InitializeVariable",
            "inputs": {
                "variables": [{"name": "varEventItemId", "type": "integer", "value": 0}]
            },
        }
        last_init = "INIT_varEventItemId"

    body_actions = {
        "CMP_Site_Config": {
            # スコープに入れる場合、先頭のアクションは runAfter を空にする
            "runAfter": {} if error_logging else {last_init: ["Succeeded"]},
            "type": "Switch",
            "expression": "@triggerBody()?['SiteCode']",
            "cases": site_cases,
            "default": {
                "actions": {
                    "END_Invalid_Site": terminate("Failed", "CFG-001", "unknown site code")
                }
            },
        },
        "CMP_Intensity_Value": {
            "runAfter": {"CMP_Site_Config": ["Succeeded"]},
            "type": "Switch",
            "expression": "@triggerBody()?['IntensityCode']",
            "cases": intensity_cases,
            "default": {
                "actions": {
                    "END_Invalid_Intensity": terminate(
                        "Failed", "SRC-003", "invalid intensity code"
                    )
                }
            },
        },
        "CHK_Threshold_Met": {
            "runAfter": {"CMP_Intensity_Value": ["Succeeded"]},
            "type": "If",
            "expression": {
                "and": [
                    {
                        "greaterOrEquals": [
                            "@variables('varIntensityValue')",
                            "@variables('varSiteConfig')?['ThresholdValue']",
                        ]
                    }
                ]
            },
            "actions": threshold_actions,
            # 閾値未満は異常ではなく正常系のため、成功で終了する
            "else": {"actions": {"END_Below_Threshold": terminate("Succeeded")}},
        },
    }

    top_level_actions = dict(init_actions)
    if error_logging:
        top_level_actions["SCOPE_Try"] = scope(body_actions, {last_init: ["Succeeded"]})
        top_level_actions["SCOPE_Catch"] = scope(
            build_catch_actions(
                cfg,
                log_list_id,
                log_columns,
                # イベント作成前に落ちた場合は EventID が無いので、時刻でキーを作る
                (
                    "@{if(equals(variables('varEventID'), ''), "
                    "concat('ERR-EQ06-', formatDateTime(utcNow(), 'yyyyMMdd-HHmmss')), "
                    "variables('varEventID'))}"
                ),
                build_close_action(cfg, update_action, "Error", {}) if close_event else None,
            ),
            {"SCOPE_Try": ["Failed", "TimedOut"]},
        )
    else:
        top_level_actions.update(body_actions)

    definition = {
        "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {
            "$connections": {"defaultValue": {}, "type": "Object"},
            "$authentication": {"defaultValue": {}, "type": "SecureObject"},
        },
        "triggers": {
            "manual": {
                "type": "Request",
                "kind": "Button",
                "inputs": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "SiteCode": {
                                "title": "SiteCode",
                                "type": "string",
                                "description": "OITA / OSAKA / TOKYO",
                                "x-ms-dynamically-added": True,
                            },
                            "IntensityCode": {
                                "title": "IntensityCode",
                                "type": "string",
                                "description": "1,2,3,4,5-,5+,6-,6+,7",
                                "x-ms-dynamically-added": True,
                            },
                            "Epicenter": {
                                "title": "Epicenter",
                                "type": "string",
                                "description": "震源地(任意)",
                                "x-ms-dynamically-added": True,
                            },
                            "IsTest": {
                                "title": "IsTest",
                                "type": "boolean",
                                "description": "訓練の場合はYes",
                                "x-ms-dynamically-added": True,
                            },
                        },
                        "required": ["SiteCode", "IntensityCode", "IsTest"],
                    }
                },
            }
        },
        "actions": top_level_actions,
    }

    return {
        "properties": {
            "connectionReferences": {
                "shared_sharepointonline": {
                    "runtimeSource": "invoker",
                    "connection": {
                        "connectionReferenceLogicalName": cfg["connectionReferences"][
                            "sharepoint"
                        ]
                    },
                    "api": {"name": "shared_sharepointonline"},
                },
                "shared_teams": {
                    "runtimeSource": "invoker",
                    "connection": {
                        "connectionReferenceLogicalName": cfg["connectionReferences"][
                            "teams"
                        ]
                    },
                    "api": {"name": "shared_teams"},
                },
            },
            "definition": definition,
            "templateName": None,
        },
        "schemaVersion": "1.0.0.0",
    }


def build_eq05(cfg, cards_dir):
    """EQ05_Status_Summary_DEV(未回答者・被災者の定期集計)。

    AlertStatusがOpenのイベントごとに、対象者数・回答数・未回答数・被災者数を
    数えて拠点のチャネルへ投稿する。EQ06の実行中(回答待ちの間)に、
    誰がまだ回答していないかを可視化するのが目的。
    """
    site_url = cfg["sharePointSiteUrl"]
    lists = cfg["listIds"]
    columns = cfg["columnInternalNames"]

    def col(list_name, display_name):
        try:
            return columns[list_name][display_name]
        except KeyError:
            raise KeyError(
                "%s の列 '%s' の内部名が deploy_config.json に未定義です"
                % (list_name, display_name)
            )

    # 拠点コードから通知先を引くための対応表。ループ内でSwitchや変数を使わずに
    # 済むよう、先頭で1つのオブジェクトにまとめてキー参照する。
    features = read_features(cfg)
    error_logging = features["errorLogging"]
    log_list_id, log_columns = (
        require_error_log_config(cfg) if error_logging else (None, None)
    )

    site_map = {
        site["siteCode"]: {
            "SiteName": site["siteName"],
            "TeamId": site["teamId"],
            "ChannelId": site["channelId"],
        }
        for site in cfg["sites"]
    }

    event = "items('LOOP_Each_Open_Event')"
    event_site = "%s?['%s']" % (event, col("EQ_Events", "SiteCode"))
    site_entry = "outputs('CMP_Site_Map')?[%s]" % event_site

    answered = "length(body('GET_Event_Responses')?['value'])"
    total = "length(body('GET_Site_Members')?['value'])"

    summary_card = load_card(
        cards_dir,
        "status_summary_card.json",
        {
            "SiteName": "@{%s?['SiteName']}" % site_entry,
            "EventID": "@{%s?['%s']}" % (event, col("EQ_Events", "Title")),
            "TotalCount": "@{%s}" % total,
            "AnsweredCount": "@{%s}" % answered,
            "UnansweredCount": "@{sub(%s,%s)}" % (total, answered),
            "AffectedCount": "@{length(body('FLT_Affected'))}",
        },
    )

    member_filter = "%s eq '@{%s}' and %s eq '%s' and %s eq '%s'" % (
        col("EQ_Config_Members", "SiteCode"),
        event_site,
        col("EQ_Config_Members", "IsActive"),
        cfg.get("memberFlagValues", {}).get("active", "TRUE"),
        col("EQ_Config_Members", "IsManager"),
        cfg.get("memberFlagValues", {}).get("notManager", "FALSE"),
    )

    body_actions = {
        "CMP_Site_Map": {"runAfter": {}, "type": "Compose", "inputs": site_map},
        "GET_Open_Events": sp_action(
            "GetItems",
            {
                "dataset": site_url,
                "table": lists["EQ_Events"],
                "$filter": "%s eq 'Open'" % col("EQ_Events", "AlertStatus"),
                "$top": 100,
            },
            {"CMP_Site_Map": ["Succeeded"]},
        ),
        "LOOP_Each_Open_Event": {
            "runAfter": {"GET_Open_Events": ["Succeeded"]},
            "type": "Foreach",
            "foreach": "@body('GET_Open_Events')?['value']",
            "actions": {
                "GET_Site_Members": sp_action(
                    "GetItems",
                    {
                        "dataset": site_url,
                        "table": lists["EQ_Config_Members"],
                        "$filter": member_filter,
                        "$top": 500,
                    },
                    {},
                ),
                "GET_Event_Responses": sp_action(
                    "GetItems",
                    {
                        "dataset": site_url,
                        "table": lists["EQ_Responses"],
                        "$filter": "%s eq '@{%s?['%s']}'"
                        % (
                            col("EQ_Responses", "EventID"),
                            event,
                            col("EQ_Events", "Title"),
                        ),
                        "$top": 500,
                    },
                    {"GET_Site_Members": ["Succeeded"]},
                ),
                # 被災者数は「配列のフィルター」で絞ってから件数を数える
                # (式には filter 関数が無いため)
                "FLT_Affected": {
                    "runAfter": {"GET_Event_Responses": ["Succeeded"]},
                    "type": "Query",
                    "inputs": {
                        "from": "@body('GET_Event_Responses')?['value']",
                        "where": "@equals(item()?['%s'],'Affected')"
                        % col("EQ_Responses", "SafetyStatus"),
                    },
                },
                "TM_Post_Summary": teams_post_card(
                    {
                        "poster": "Flow bot",
                        "location": "Channel",
                        "body/recipient/groupId": "@%s?['TeamId']" % site_entry,
                        "body/recipient/channelId": "@%s?['ChannelId']" % site_entry,
                        "body/messageBody": summary_card,
                    },
                    {"FLT_Affected": ["Succeeded"]},
                ),
            },
        },
    }

    top_level_actions = {}
    if error_logging:
        # EQ05 は15分ごとに自動で動くため、失敗しても実行履歴を見ない限り気づけない。
        # EQ06 と同じ形で EQ_Received_Items へ記録する。
        top_level_actions["SCOPE_Try"] = scope(body_actions, {})
        top_level_actions["SCOPE_Catch"] = scope(
            build_catch_actions(
                cfg,
                log_list_id,
                log_columns,
                "@{concat('ERR-EQ05-', formatDateTime(utcNow(), 'yyyyMMdd-HHmmss'))}",
            ),
            {"SCOPE_Try": ["Failed", "TimedOut"]},
        )
    else:
        top_level_actions = body_actions

    definition = {
        "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {
            "$connections": {"defaultValue": {}, "type": "Object"},
            "$authentication": {"defaultValue": {}, "type": "SecureObject"},
        },
        "triggers": {
            "Recurrence": {
                "type": "Recurrence",
                "recurrence": {
                    "frequency": "Minute",
                    "interval": cfg.get("summaryIntervalMinutes", 15),
                },
            }
        },
        "actions": top_level_actions,
    }

    return {
        "properties": {
            "connectionReferences": {
                "shared_sharepointonline": {
                    "runtimeSource": "invoker",
                    "connection": {
                        "connectionReferenceLogicalName": cfg["connectionReferences"][
                            "sharepoint"
                        ]
                    },
                    "api": {"name": "shared_sharepointonline"},
                },
                "shared_teams": {
                    "runtimeSource": "invoker",
                    "connection": {
                        "connectionReferenceLogicalName": cfg["connectionReferences"][
                            "teams"
                        ]
                    },
                    "api": {"name": "shared_teams"},
                },
            },
            "definition": definition,
            "templateName": None,
        },
        "schemaVersion": "1.0.0.0",
    }


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
    """Solutionのソースツリー(Other/ と Workflows/)を書き出す。"""
    workflows_dir = os.path.join(out_dir, "Workflows")
    other_dir = os.path.join(out_dir, "Other")
    os.makedirs(workflows_dir, exist_ok=True)
    os.makedirs(other_dir, exist_ok=True)

    root_components = []
    for name, (guid, flow_json) in flows.items():
        guid_lower = guid.lower()
        guid_upper = guid.upper()
        base = "%s-%s" % (name, guid_upper)

        json_path = os.path.join(workflows_dir, base + ".json")
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(flow_json, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

        xml_path = os.path.join(workflows_dir, base + ".json.data.xml")
        with open(xml_path, "w", encoding="utf-8") as fh:
            fh.write(
                WORKFLOW_METADATA_TEMPLATE.format(
                    guid_lower=guid_lower, guid_upper=guid_upper, name=name
                )
            )

        root_components.append(
            '      <RootComponent type="29" id="{%s}" behavior="0" />' % guid_lower
        )

    with open(os.path.join(other_dir, "Customizations.xml"), "w", encoding="utf-8") as fh:
        fh.write(CUSTOMIZATIONS_XML)

    solution_cfg = cfg["solution"]
    with open(os.path.join(other_dir, "Solution.xml"), "w", encoding="utf-8") as fh:
        fh.write(
            SOLUTION_XML_TEMPLATE.format(
                solution_name=solution_cfg["uniqueName"],
                publisher_name=solution_cfg["publisherUniqueName"],
                publisher_prefix=solution_cfg["publisherPrefix"],
                root_components="\n".join(root_components),
            )
        )

    with open(os.path.join(other_dir, "Relationships.xml"), "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n<Relationships />\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="deploy_config.json", help="実値の設定ファイル")
    parser.add_argument("--out", default="./src", help="Solutionソースの出力先")
    parser.add_argument(
        "--cards", default="../cards", help="Adaptive Card(JSON)のあるフォルダ"
    )
    args = parser.parse_args()

    if not os.path.exists(args.config):
        sys.exit(
            "設定ファイルが見つかりません: %s\n"
            "deploy_config.example.json をコピーして実値を入れてください。" % args.config
        )

    with open(args.config, encoding="utf-8-sig") as fh:
        cfg = json.load(fh)

    # 生成の前に、いま誰へ届く設定になっているかを必ず表示する。
    # 本番宛先へ切り替わったことに気づかないまま実行するのが一番危ない。
    override = cfg.get("testRecipientOverride", "").strip()
    if override:
        print("[検証モード] testRecipientOverride が設定されています。")
        print("            個人カード・上司通知は名簿を無視し、検証者だけに届きます。")
    else:
        print("*" * 70)
        print("[本番宛先モード] testRecipientOverride が空です。")
        print("  EQ_Config_Members に登録された実在メンバー全員へ、実際にカードが届きます。")
        print("  訓練の予定が無い場合は、設定を戻してから生成し直してください。")
        print("*" * 70)

    features = read_features(cfg)
    print(
        "機能: errorLogging=%s / eventClose=%s"
        % (features["errorLogging"], features["eventClose"])
    )
    print("")

    builders = {
        "EQ06_Manual_Drill_DEV": build_eq06,
        "EQ05_Status_Summary_DEV": build_eq05,
    }
    # workflowIds に載っているフローだけを生成する(段階的に増やせるように)
    flows = {
        name: (cfg["workflowIds"][name], builder(cfg, args.cards))
        for name, builder in builders.items()
        if name in cfg["workflowIds"]
    }

    write_solution(args.out, cfg, flows)

    print("生成しました: %s" % os.path.abspath(args.out))
    for name in flows:
        print("  - %s" % name)
    print("")
    print("次のコマンドでインポートしてください:")
    print("  pac solution pack --zipfile ./EQSafetyCheckin.zip --folder %s" % args.out)
    print("  pac solution import --environment <ENV_ID> --path ./EQSafetyCheckin.zip")


if __name__ == "__main__":
    main()
