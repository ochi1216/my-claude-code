#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_config.json へ、20260901_02 で追加した設定項目を書き足す。

手で編集するとカンマの付け忘れなどで壊しやすいため、追記を自動化する。

この実行で追加されるのは以下の3つ。**すでにある値は書き換えない。**

  - columnInternalNames.EQ_Received_Items … 列内部名(2026-09-01実測)
  - features                              … errorLogging / eventClose の機能フラグ
  - sharePointUpdateAction                … SharePoint「項目の更新」アクションの実測値の枠

listIds.EQ_Received_Items が無い場合は、--received-items-list-id で渡すか、
実行中の問い合わせに答えて入力する(リストGUIDは社内情報のため、この
スクリプトには書き込まない)。

使い方(このフォルダで実行する):

    python update_deploy_config_20260901_01.py
    python update_deploy_config_20260901_01.py --enable-error-logging
    python update_deploy_config_20260901_01.py --received-items-list-id <GUID>

書き換える前に deploy_config.json.bak_<日時> という控えを作る。

エラー処理の動作確認用に、わざと失敗する設定の写しも書き出せる。

    python update_deploy_config_20260901_01.py --write-error-test-copy deploy_config_errortest.json

この場合、元の deploy_config.json には一切触らない。
"""

import argparse
import collections
import datetime
import io
import json
import os
import re
import shutil
import sys

# 2026-09-01に実測した列内部名(evidence/sharepoint_internal_names.json 参照)。
# 内部名は個人情報・社内識別子を含まないため、ここに書いてよい。
RECEIVED_ITEMS_COLUMNS = collections.OrderedDict([
    ("Title", "Title"),
    ("ProcessingStatus", "field_4"),
    ("ErrorCode", "field_5"),
    ("ErrorDetail", "field_6"),
])

GUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                          r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# 存在しないリストGUID。エラー処理の動作確認で、SP_Create_Event をわざと失敗させる。
# このアクションはフローの最初のコネクタ呼び出しであり、ここで落とせば Teams への
# 投稿は一切起きない(誰にもカードが飛ばない)。
MISSING_LIST_ID = "00000000-0000-0000-0000-000000000000"


def load_config(path):
    """設定を読み込む。キーの順番とBOMの有無は元のまま保つ。"""
    with io.open(path, "rb") as fh:
        raw = fh.read()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    try:
        cfg = json.loads(text, object_pairs_hook=collections.OrderedDict)
    except ValueError as exc:
        raise SystemExit(
            "deploy_config.json を読めませんでした(JSONとして壊れています)。\n"
            "  %s\n"
            "手で編集した直後であれば、カンマの付け忘れや過剰なカンマを確認してください。" % exc
        )
    return cfg, has_bom


def save_config(path, cfg, has_bom):
    text = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
    with io.open(path, "wb") as fh:
        if has_bom:
            fh.write(b"\xef\xbb\xbf")
        fh.write(text.encode("utf-8"))


def insert_before(cfg, new_key, new_value, before_key):
    """既存のキー順を保ったまま、指定キーの手前に差し込む。

    OrderedDict には途中挿入が無いため、作り直して入れ替える。
    設定ファイルを人が読むときに、関係する項目が近くに並んでいた方が分かりやすい。
    """
    if new_key in cfg:
        return
    rebuilt = collections.OrderedDict()
    inserted = False
    for key, value in cfg.items():
        if key == before_key and not inserted:
            rebuilt[new_key] = new_value
            inserted = True
        rebuilt[key] = value
    if not inserted:
        rebuilt[new_key] = new_value
    cfg.clear()
    cfg.update(rebuilt)


def ask_list_id():
    """listIds.EQ_Received_Items が無いとき、対話で受け取る。"""
    print("")
    print("listIds に EQ_Received_Items がありません。")
    print("SharePointのリストGUIDを入力してください(空のままEnterで、この項目は追加しません)。")
    print("  例: 00000000-1111-2222-3333-444444444444")
    try:
        answer = raw_input("EQ_Received_Items のリストGUID: ")  # noqa: F821
    except NameError:
        answer = input("EQ_Received_Items のリストGUID: ")
    return answer.strip()


def write_error_test_copy(cfg, has_bom, source_path, dest_path):
    """EQ_EventsのリストGUIDだけを存在しない値に差し替えた写しを書き出す。

    元の設定には触らない。この写しから生成したフローは、最初のSharePoint
    アクション(SP_Create_Event)で必ず失敗するため、Teamsへの投稿が一度も
    起きないまま SCOPE_Catch の動作だけを確かめられる。
    """
    if os.path.abspath(dest_path) == os.path.abspath(source_path):
        raise SystemExit("写しの書き出し先が元のファイルと同じです: %s" % dest_path)
    if not cfg.get("features", {}).get("errorLogging"):
        raise SystemExit(
            "features.errorLogging が有効になっていません。\n"
            "先に --enable-error-logging を付けて実行してください"
            "(エラー処理が入っていないフローでは、この確認はできません)。"
        )

    broken = json.loads(json.dumps(cfg), object_pairs_hook=collections.OrderedDict)
    broken["listIds"]["EQ_Events"] = MISSING_LIST_ID
    save_config(dest_path, broken, has_bom)
    load_config(dest_path)

    print("")
    print("書き出しました: %s" % dest_path)
    print("  元の %s は変更していません。" % source_path)
    print("")
    print("この写しから生成したフローは、EQ_Events への書き込みで必ず失敗します。")
    print("Teamsへの投稿はその手前にも後にも起きないため、誰にもカードは届きません。")
    print("")
    print("確認のあとは、必ず元の設定から生成し直してインポートし直してください:")
    print("  python build_flows_20260901_02.py --config %s --out .\\src --cards ..\\cards"
          % source_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="deploy_config.json", help="書き換える設定ファイル")
    parser.add_argument("--received-items-list-id", default="",
                        help="listIds.EQ_Received_Items に入れるリストGUID(未設定の場合のみ使う)")
    parser.add_argument("--enable-error-logging", action="store_true",
                        help="features.errorLogging を true にする")
    parser.add_argument("--enable-event-close", action="store_true",
                        help="features.eventClose を true にする("
                             "sharePointUpdateAction の実測値が必要)")
    parser.add_argument("--no-prompt", action="store_true",
                        help="リストGUIDを対話で聞かない(自動実行向け)")
    parser.add_argument("--write-error-test-copy", default="",
                        help="エラー処理の動作確認用に、EQ_EventsのリストGUIDだけを"
                             "存在しない値へ差し替えた写しを、指定したパスへ書き出す"
                             "(元のファイルは変更しない)")
    args = parser.parse_args()

    if not os.path.exists(args.config):
        raise SystemExit(
            "設定ファイルが見つかりません: %s\n"
            "power_automate_safety_checkin/solution フォルダで実行してください。" % args.config
        )

    cfg, has_bom = load_config(args.config)

    if args.write_error_test_copy:
        write_error_test_copy(cfg, has_bom, args.config, args.write_error_test_copy)
        return

    changes = []
    warnings = []

    # --- 1. 列内部名 ---------------------------------------------------------
    columns = cfg.setdefault("columnInternalNames", collections.OrderedDict())
    existing = columns.get("EQ_Received_Items")
    if not isinstance(existing, dict):
        columns["EQ_Received_Items"] = collections.OrderedDict(RECEIVED_ITEMS_COLUMNS)
        changes.append("columnInternalNames.EQ_Received_Items を追加しました")
    else:
        added = [name for name, internal in RECEIVED_ITEMS_COLUMNS.items()
                 if name not in existing and existing.setdefault(name, internal)]
        if added:
            changes.append("columnInternalNames.EQ_Received_Items へ %s を追加しました"
                           % ", ".join(added))
        else:
            changes.append("columnInternalNames.EQ_Received_Items は設定済みでした(変更なし)")

    # --- 2. リストGUID -------------------------------------------------------
    list_ids = cfg.setdefault("listIds", collections.OrderedDict())
    current = list_ids.get("EQ_Received_Items", "")
    if not current or current.startswith("<"):
        list_id = args.received_items_list_id.strip()
        if not list_id and not args.no_prompt and sys.stdin.isatty():
            list_id = ask_list_id()
        if list_id:
            if not GUID_PATTERN.match(list_id):
                raise SystemExit(
                    "リストGUIDの形式が違います: %r\n"
                    "8-4-4-4-12 桁の16進数(ハイフン区切り)で指定してください。" % list_id
                )
            list_ids["EQ_Received_Items"] = list_id.lower()
            changes.append("listIds.EQ_Received_Items を設定しました")
        else:
            warnings.append(
                "listIds.EQ_Received_Items が未設定のままです。"
                "features.errorLogging を有効にすると生成が止まります。"
            )
    else:
        changes.append("listIds.EQ_Received_Items は設定済みでした(変更なし)")

    # --- 3. 機能フラグ -------------------------------------------------------
    if "features" not in cfg:
        insert_before(cfg, "features", collections.OrderedDict([
            ("errorLogging", False), ("eventClose", False),
        ]), "testRecipientOverride")
        changes.append("features を追加しました(どちらも false)")
    features = cfg["features"]
    if args.enable_error_logging and not features.get("errorLogging"):
        features["errorLogging"] = True
        changes.append("features.errorLogging を true にしました")
    if args.enable_event_close and not features.get("eventClose"):
        features["eventClose"] = True
        changes.append("features.eventClose を true にしました")

    # --- 4. SharePoint「項目の更新」アクションの枠 ---------------------------
    if "sharePointUpdateAction" not in cfg:
        insert_before(cfg, "sharePointUpdateAction", collections.OrderedDict([
            ("operationId", "<未実測>"), ("idParameter", "<未実測>"),
        ]), "testRecipientOverride")
        changes.append("sharePointUpdateAction を追加しました(未実測のまま)")
    else:
        changes.append("sharePointUpdateAction は設定済みでした(変更なし)")

    # --- 書き出し ------------------------------------------------------------
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = "%s.bak_%s" % (args.config, stamp)
    shutil.copy2(args.config, backup)
    save_config(args.config, cfg, has_bom)

    # 書いたものを読み直して、壊していないことを確かめる
    load_config(args.config)

    print("")
    print("控えを作りました: %s" % backup)
    print("")
    for line in changes:
        print("  - %s" % line)
    for line in warnings:
        print("  ! %s" % line)

    override = cfg.get("testRecipientOverride", "").strip()
    print("")
    if override:
        print("[検証モード] testRecipientOverride は設定されたままです。")
        print("            個人カード・上司通知は検証者だけに届きます。")
    else:
        print("*" * 70)
        print("[本番宛先モード] testRecipientOverride が空です。")
        print("  この設定のまま実行すると、実在メンバー全員へカードが届きます。")
        print("*" * 70)
    print("機能: errorLogging=%s / eventClose=%s"
          % (cfg["features"].get("errorLogging"), cfg["features"].get("eventClose")))
    print("")
    print("次のコマンドで生成できます:")
    print("  python build_flows_20260901_02.py --config %s --out .\\src --cards ..\\cards"
          % args.config)


if __name__ == "__main__":
    main()
