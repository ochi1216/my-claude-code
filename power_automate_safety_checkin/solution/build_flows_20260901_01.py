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

    python build_flows_20260901_01.py --config deploy_config.json --out ./src
    pac solution pack --zipfile ./EQSafetyCheckin.zip --folder ./src
    pac solution import --environment <ENV_ID> --path ./EQSafetyCheckin.zip

コネクタの operationId / パラメータ名は、実テナントからエクスポートした
フローの実測値に基づく(docs/GATE_STATUS.md の Gate B/D 参照)。
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


def terminate(status, code=None, message=None):
    """フローを終了するアクション。閾値未満のような正常終了にも使う。"""
    inputs = {"runStatus": status}
    if status == "Failed":
        inputs["runError"] = {"code": code or "", "message": message or ""}
    return {"runAfter": {}, "type": "Terminate", "inputs": inputs}


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

    # 検証段階では、名簿に実在の同僚が入っていても訓練カードが飛ばないようにする。
    # testRecipientOverride が空でなければ、IsTest=true の実行に限りその宛先へ送る。
    # 本番運用に移る際はこの設定を空にすること。
    member_email = "items('LOOP_Each_Member')?['%s']" % col("EQ_Config_Members", "Email")
    override = cfg.get("testRecipientOverride", "").strip()
    if override:
        recipient_expr = "@if(triggerBody()?['IsTest'], '%s', %s)" % (override, member_email)
    else:
        recipient_expr = "@%s" % member_email

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
            {"CMP_EventID": ["Succeeded"]},
        ),
        "CMP_OccurredAtJST": {
            "runAfter": {"SP_Create_Event": ["Succeeded"]},
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
                        # 同時実行は初期値1。Gate B確認後に引き上げを検討する
                        "runtimeConfiguration": {"concurrency": {"repetitions": 1}},
                        "actions": {
                            "TM_Post_CheckIn_Card": teams_post_card(
                                {
                                    "poster": "Flow bot",
                                    "location": "Chat with Flow bot",
                                    "body/recipient": recipient_expr,
                                    "body/messageBody": checkin_card,
                                },
                                {},
                            )
                        },
                    }
                }
            },
        },
    }

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
        "actions": {
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
                    "variables": [
                        {"name": "varIntensityValue", "type": "integer", "value": 0}
                    ]
                },
            },
            "CMP_Site_Config": {
                "runAfter": {"INIT_varIntensityValue": ["Succeeded"]},
                "type": "Switch",
                "expression": "@triggerBody()?['SiteCode']",
                "cases": site_cases,
                "default": {
                    "actions": {
                        "END_Invalid_Site": terminate(
                            "Failed", "CFG-001", "unknown site code"
                        )
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
        },
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

    flows = {
        "EQ06_Manual_Drill_DEV": (
            cfg["workflowIds"]["EQ06_Manual_Drill_DEV"],
            build_eq06(cfg, args.cards),
        )
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
