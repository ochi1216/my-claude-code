#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_flows_20260901_02.py の生成物を、テナントへ入れずに検証する。

このプロジェクトのフローはWindows/Power Automate環境でしか実行できず、開発を
行っているリモートセッション(Linuxコンテナ)からはインポートも実行もできない。
そこで、生成されたフロー定義(JSON)そのものを機械的に点検する。

インポート時に弾かれる典型的な間違いと、実行時に値が壊れる典型的な間違いを
対象にしている。実機での動作確認の代わりにはならないが、「インポートして初めて
気づく」類の失敗はここで潰せる。

使い方(このフォルダで実行する。deploy_config.json は不要):

    python verify_flows_20260901_01.py

確認する項目:

  1. 機能フラグを全てオフにしたとき、20260901_01 と1バイトも変わらない出力になる
  2. すべての runAfter が、同じスコープ内に実在するアクションを指している
  3. アクション名がフロー全体で一意である(Power Automateの制約)
  4. Terminate が Foreach / Until の中に入っていない(入れるとインポートで弾かれる)
  5. InitializeVariable がフローの最上位にしか無い(同上)
  6. 参照・代入している変数がすべて最上位で初期化されている
  7. 並列ループの中で SetVariable を使っていない(値が混ざる)
  8. 生成物に未実測のプレースホルダ(<...>)が残っていない
  9. 未実測のまま機能を有効にすると、生成が止まる(推測値で作らせない)
 10. エラー処理・クローズ処理が意図した位置と内容になっている
"""

import copy
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CARDS = os.path.join(os.path.dirname(HERE), "cards")

FAILURES = []
CHECKS = [0]


def check(ok, label, detail=""):
    CHECKS[0] += 1
    if ok:
        print("  ok   %s" % label)
    else:
        print("  NG   %s  %s" % (label, detail))
        FAILURES.append(label)


# 実値は使わない。構造だけを見るためのダミー設定。
BASE_CONFIG = {
    "sharePointSiteUrl": "https://example.sharepoint.com/sites/Dummy",
    "listIds": {
        "EQ_Events": "11111111-1111-1111-1111-111111111111",
        "EQ_Config_Members": "22222222-2222-2222-2222-222222222222",
        "EQ_Responses": "33333333-3333-3333-3333-333333333333",
        "EQ_Received_Items": "44444444-4444-4444-4444-444444444444",
    },
    "columnInternalNames": {
        "EQ_Events": {
            "Title": "Title", "SiteCode": "field_2", "OccurredAt": "field_3",
            "Epicenter": "field_5", "SiteIntensityCode": "field_7",
            "SiteIntensityValue": "field_8", "AlertStatus": "field_9",
            "StartedBy": "field_10", "IsTest": "field_11",
        },
        "EQ_Config_Members": {
            "Title": "Title", "DisplayName": "field_1", "Email": "field_2",
            "SiteCode": "field_3", "IsActive": "field_4", "IsManager": "field_5",
            "EscalationOrder": "field_6",
        },
        "EQ_Responses": {
            "Title": "Title", "EventID": "field_1", "EmployeeID": "field_2",
            "Email": "field_3", "ResponseCode": "field_4", "SafetyStatus": "field_5",
            "WorkStatus": "field_6", "RespondedAt": "field_7", "Comment": "field_8",
            "Revision": "field_9",
        },
        # 実測値(2026-09-01)。CreatedAt 列は存在しないため入れていない。
        "EQ_Received_Items": {
            "Title": "Title", "ProcessingStatus": "field_4", "ErrorCode": "field_5",
            "ErrorDetail": "field_6",
        },
    },
    "memberFlagValues": {"active": "TRUE", "notManager": "FALSE", "isManager": "TRUE"},
    "sharePointUpdateAction": {"operationId": "DUMMY_UpdateItem", "idParameter": "id"},
    "testRecipientOverride": "tester@example.com",
    "responseTimeout": "PT1H",
    "loopConcurrency": 20,
    "summaryIntervalMinutes": 15,
    "connectionReferences": {"sharepoint": "njp_sp_dummy", "teams": "njp_teams_dummy"},
    "sites": [
        {"siteCode": "TOKYO", "siteName": "Japan Tokyo Site", "thresholdValue": 50,
         "teamId": "TEAM_DUMMY1", "channelId": "CHANNEL_DUMMY1"},
        {"siteCode": "OITA", "siteName": "Japan Oita Site", "thresholdValue": 50,
         "teamId": "TEAM_DUMMY2", "channelId": "CHANNEL_DUMMY2"},
    ],
    "workflowIds": {
        "EQ06_Manual_Drill_DEV": "11111111-2222-3333-4444-555555555555",
        "EQ05_Status_Summary_DEV": "22222222-3333-4444-5555-666666666666",
    },
    "solution": {"uniqueName": "EQSafetyCheckinSolution",
                 "publisherUniqueName": "NexperiaJP", "publisherPrefix": "njp"},
}


def list_files(root):
    """ディレクトリ配下のファイルを、rootからの相対パスの集合で返す。"""
    found = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            found.add(os.path.relpath(full, root).replace("\\", "/"))
    return found


def compare_trees(old_dir, new_dir):
    """2つのディレクトリを再帰的に比較し、違いを1行ずつ並べて返す。

    Windowsには diff コマンドが無いため、外部コマンドを使わずに自前で比較する。
    """
    old_files, new_files = list_files(old_dir), list_files(new_dir)
    differences = []
    for name in sorted(old_files - new_files):
        differences.append("旧のみに存在: %s" % name)
    for name in sorted(new_files - old_files):
        differences.append("新のみに存在: %s" % name)
    for name in sorted(old_files & new_files):
        with open(os.path.join(old_dir, name), "rb") as fh:
            old_bytes = fh.read()
        with open(os.path.join(new_dir, name), "rb") as fh:
            new_bytes = fh.read()
        if old_bytes != new_bytes:
            differences.append("内容が異なる: %s" % name)
    return differences


def load_module(filename, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config_with(**features):
    cfg = copy.deepcopy(BASE_CONFIG)
    cfg["features"] = features
    return cfg


def walk(actions, path, container_kind, out):
    """アクションツリーをたどり、(名前, 定義, 親の種類, 同スコープの名前, 経路) を集める。"""
    siblings = set(actions.keys())
    for name, action in actions.items():
        out.append((name, action, container_kind, siblings, path))
        kind = action.get("type")
        child_path = path + "/" + name
        for key in ("actions", "else"):
            child = action.get(key)
            if key == "else":
                child = (child or {}).get("actions")
            if isinstance(child, dict):
                walk(child, child_path, kind, out)
        for case in (action.get("cases") or {}).values():
            walk(case.get("actions", {}), child_path, kind, out)
        default = (action.get("default") or {}).get("actions")
        if isinstance(default, dict):
            walk(default, child_path, kind, out)


def check_structure(label, definition):
    """どの機能の組み合わせでも満たすべき、共通の構造条件を確認する。"""
    print("")
    print("[%s]" % label)
    nodes = []
    walk(definition["actions"], "", "root", nodes)
    text = json.dumps(definition, ensure_ascii=False)

    bad_refs = [(n, dep, p) for n, a, _, sib, p in nodes
                for dep in (a.get("runAfter") or {}) if dep not in sib]
    check(not bad_refs, "runAfter の参照先がすべて同一スコープ内に実在する", str(bad_refs[:5]))

    names = [n for n, _, _, _, _ in nodes]
    dups = sorted({n for n in names if names.count(n) > 1})
    check(not dups, "アクション名がフロー全体で一意", str(dups))

    in_loop = [n for n, a, kind, _, p in nodes
               if a.get("type") == "Terminate"
               and (kind in ("Foreach", "Until") or "/LOOP_" in p)]
    check(not in_loop, "Terminate がループの外にある", str(in_loop))

    nested_init = [n for n, a, kind, _, _ in nodes
                   if a.get("type") == "InitializeVariable" and kind != "root"]
    check(not nested_init, "InitializeVariable が最上位のみ", str(nested_init))

    declared = {v["name"] for _, a, _, _, _ in nodes
                if a.get("type") == "InitializeVariable"
                for v in a["inputs"]["variables"]}
    used = set(re.findall(r"variables\('([A-Za-z0-9_]+)'\)", text))
    check(used <= declared, "参照している変数がすべて初期化済み",
          "未初期化: %s" % sorted(used - declared))

    assigned = {a["inputs"]["name"] for _, a, _, _, _ in nodes
                if a.get("type") == "SetVariable"}
    check(assigned <= declared, "SetVariable の対象がすべて初期化済み",
          str(sorted(assigned - declared)))

    in_parallel = [n for n, a, _, _, p in nodes
                   if a.get("type") == "SetVariable" and "/LOOP_" in p]
    check(not in_parallel, "並列ループ内で SetVariable を使っていない", str(in_parallel))

    check("<" not in text.replace("<br>", ""), "未実測プレースホルダが残っていない")


def check_error_handling(label, definition, expect_event_close):
    """SCOPE_Try / SCOPE_Catch が意図した形になっているか。"""
    print("")
    print("[%s] エラー処理" % label)
    top = definition["actions"]
    check("SCOPE_Try" in top and "SCOPE_Catch" in top, "SCOPE_Try / SCOPE_Catch が最上位にある")
    check(top["SCOPE_Catch"]["runAfter"] == {"SCOPE_Try": ["Failed", "TimedOut"]},
          "SCOPE_Catch は SCOPE_Try の Failed / TimedOut で動く",
          str(top["SCOPE_Catch"]["runAfter"]))
    catch = top["SCOPE_Catch"]["actions"]
    check("SP_Log_Error" in catch, "EQ_Received_Items へ記録するアクションがある")
    params = catch["SP_Log_Error"]["inputs"]["parameters"]
    check(params["table"] == BASE_CONFIG["listIds"]["EQ_Received_Items"],
          "記録先が EQ_Received_Items になっている")
    check(params["item/field_4"] == "Error", "ProcessingStatus に Error を書く")
    check(params["item/field_6"] == "@outputs('CMP_Error_Message')",
          "ErrorDetail にエラー内容を書く")
    # CreatedAt 列が無いリストでも、余計な列へ書きにいかないこと
    check(not any(key.startswith("item/") and key not in
                  ("item/Title", "item/field_4", "item/field_5", "item/field_6")
                  for key in params),
          "存在しない列へ書き込もうとしていない", str(sorted(params)))
    check(catch["END_Failed"]["inputs"]["runStatus"] == "Failed",
          "最後に実行を失敗として終わらせる(成功扱いで隠さない)")
    check(("CHK_Event_Created" in catch) is expect_event_close,
          "失敗時のイベント更新は eventClose が有効なときだけ入る")
    if expect_event_close:
        mark = catch["CHK_Event_Created"]["actions"]["SP_Mark_Event_Error"]
        check(mark["inputs"]["parameters"]["item/field_9"] == "Error",
              "失敗時は AlertStatus を Error にする")


def check_event_close(label, definition, wrapped):
    """クローズ処理が、全員分のループが終わったあとに動くか。"""
    print("")
    print("[%s] クローズ処理" % label)
    root = definition["actions"]
    body = root["SCOPE_Try"]["actions"] if wrapped else root
    th = body["CHK_Threshold_Met"]["actions"]
    check(th["SET_varEventItemId"]["inputs"]["value"] == "@body('SP_Create_Event')?['ID']",
          "項目IDはイベント作成の応答から取っている")
    check(th["SP_Close_Event"]["runAfter"] == {"CHK_Members_Found": ["Succeeded"]},
          "SP_Close_Event は全員分のループが終わってから動く",
          str(th["SP_Close_Event"]["runAfter"]))
    params = th["SP_Close_Event"]["inputs"]["parameters"]
    check(params["item/field_9"] == "Closed", "正常終了時は AlertStatus を Closed にする")
    check(params["id"] == "@variables('varEventItemId')", "更新対象を項目IDで指している")
    check(params["table"] == BASE_CONFIG["listIds"]["EQ_Events"], "更新先が EQ_Events")


def main():
    mod01 = load_module("build_flows_20260901_01.py", "build_flows_v01")
    mod02 = load_module("build_flows_20260901_02.py", "build_flows_v02")

    def generate(module, cfg, out_dir):
        flows = {
            "EQ06_Manual_Drill_DEV": (cfg["workflowIds"]["EQ06_Manual_Drill_DEV"],
                                      module.build_eq06(cfg, CARDS)),
            "EQ05_Status_Summary_DEV": (cfg["workflowIds"]["EQ05_Status_Summary_DEV"],
                                        module.build_eq05(cfg, CARDS)),
        }
        module.write_solution(out_dir, cfg, flows)

    # --- 1. 機能オフなら 20260901_01 と同一 -------------------------------
    print("[回帰] 機能フラグを全てオフにしたとき、20260901_01 と同一の出力になるか")
    tmp = tempfile.mkdtemp()
    try:
        old_dir, new_dir = os.path.join(tmp, "v01"), os.path.join(tmp, "v02")
        generate(mod01, copy.deepcopy(BASE_CONFIG), old_dir)
        generate(mod02, config_with(errorLogging=False, eventClose=False), new_dir)
        differences = compare_trees(old_dir, new_dir)
        check(not differences, "機能オフの生成物が 20260901_01 と一致",
              " / ".join(differences[:5]))
    finally:
        shutil.rmtree(tmp)

    # --- 2〜8. 4通りの組み合わせすべてで構造を点検 -------------------------
    for error_logging in (False, True):
        for event_close in (False, True):
            cfg = config_with(errorLogging=error_logging, eventClose=event_close)
            suffix = "errorLogging=%s, eventClose=%s" % (error_logging, event_close)
            eq06 = mod02.build_eq06(cfg, CARDS)["properties"]["definition"]
            eq05 = mod02.build_eq05(cfg, CARDS)["properties"]["definition"]
            check_structure("EQ06 / " + suffix, eq06)
            check_structure("EQ05 / " + suffix, eq05)
            if error_logging:
                check_error_handling("EQ06 / " + suffix, eq06, event_close)
                # EQ05 にはイベントの概念が無いため、失敗時のイベント更新は入らない
                check_error_handling("EQ05 / " + suffix, eq05, False)
            if event_close:
                check_event_close("EQ06 / " + suffix, eq06, wrapped=error_logging)

    # --- 9. 未実測のまま機能を有効にすると生成が止まるか -------------------
    print("")
    print("[任意列] CreatedAt 列がある場合は、そこにも発生時刻を書くか")
    cfg = config_with(errorLogging=True, eventClose=False)
    cfg["columnInternalNames"]["EQ_Received_Items"]["CreatedAt"] = "field_9"
    eq06 = mod02.build_eq06(cfg, CARDS)["properties"]["definition"]
    log_params = (eq06["actions"]["SCOPE_Catch"]["actions"]["SP_Log_Error"]
                  ["inputs"]["parameters"])
    check(log_params.get("item/field_9") == "@utcNow()",
          "CreatedAt を設定した場合は発生時刻を書く", str(sorted(log_params)))

    print("")
    print("[安全弁] 未実測のまま機能を有効にすると生成が止まるか")
    cases = [
        ("EQ_Received_Items の列内部名が未実測",
         lambda c: c["columnInternalNames"].update({"EQ_Received_Items": {
             "Title": "<未実測>", "ProcessingStatus": "<未実測>", "ErrorCode": "<未実測>",
             "ErrorDetail": "<未実測>"}})),
        ("EQ_Received_Items の ErrorDetail だけ未実測",
         lambda c: c["columnInternalNames"]["EQ_Received_Items"].update(
             {"ErrorDetail": "<未実測>"})),
        ("EQ_Received_Items のリストIDが未実測",
         lambda c: c["listIds"].update(
             {"EQ_Received_Items": "<EQ_RECEIVED_ITEMS_LIST_GUID>"})),
        # 全ゼロは書式としては正しいGUIDに見えるが、実在しないリストを指す
        ("EQ_Received_Items のリストIDが全ゼロ",
         lambda c: c["listIds"].update(
             {"EQ_Received_Items": "00000000-0000-0000-0000-000000000000"})),
        ("SharePoint更新アクションが未実測",
         lambda c: c.update({"sharePointUpdateAction": {
             "operationId": "<未実測>", "idParameter": "<未実測>"}})),
    ]
    for label, mutate in cases:
        cfg = config_with(errorLogging=True, eventClose=True)
        mutate(cfg)
        try:
            mod02.build_eq06(cfg, CARDS)
            check(False, "%s → 生成が止まる" % label, "止まらずに生成された")
        except SystemExit as exc:
            check("未実測" in str(exc) or "必要です" in str(exc),
                  "%s → 生成が止まる" % label, str(exc)[:120])

    print("")
    print("=" * 64)
    print("%d 件中 %d 件成功 / %d 件失敗"
          % (CHECKS[0], CHECKS[0] - len(FAILURES), len(FAILURES)))
    if FAILURES:
        for name in FAILURES:
            print("  失敗: %s" % name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
