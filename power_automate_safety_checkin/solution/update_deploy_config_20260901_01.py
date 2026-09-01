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

GUID_PATTERN = re.compile(r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                          r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$")

# エラー処理の動作確認で、GET_Active_Members をわざと失敗させるための列内部名。
#
# 当初は EQ_Events のリストGUIDを存在しない値にしていたが、それでは実行時ではなく
# デザイナーの保存・検証の時点で GetTable が NotFound となって弾かれ、フローが
# オフになってしまった(2026-09-01 実機で判明)。$filter は SharePoint がサーバ側で
# 評価する単なる文字列で保存時には検証されないため、フィルターに使う列の内部名を
# 差し替える方式にした。実行時に 400 (column does not exist) で失敗する。
BROKEN_COLUMN_NAME = "field_no_such_column_for_error_test"


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


def describe_guid_format(value):
    """リストGUIDの書式を、値そのものを出さずに説明する。"""
    if not value:
        return "未設定"
    if value.startswith("<"):
        return "プレースホルダのまま"
    if not GUID_PATTERN.match(value):
        return "GUIDの形式ではない(長さ %d)" % len(value)
    braces = "中かっこあり" if value.startswith("{") else "中かっこなし"
    body = value.strip("{}")
    if body.lower() == body:
        case = "小文字"
    elif body.upper() == body:
        case = "大文字"
    else:
        case = "大小混在"
    return "%s・%s" % (braces, case)


def diagnose(cfg, path):
    """設定の書式を点検する。「List not found」の切り分け用。

    SharePointコネクタの table は、環境によって中かっこ付きのGUIDが入っている
    ことがある。3リストが中かっこ付きなのに1つだけ無い、といった食い違いは
    インポートは通るのに実行・保存の時点で NotFound になるため見つけにくい。
    """
    print("")
    print("%s の点検" % path)
    print("")
    print("listIds の書式(値そのものは表示しません):")
    formats = {}
    for name, value in cfg.get("listIds", {}).items():
        if name.startswith("_"):
            continue
        shape = describe_guid_format(value if isinstance(value, str) else "")
        formats.setdefault(shape, []).append(name)
        print("  %-20s : %s" % (name, shape))

    print("")
    if len(formats) > 1:
        print("!! 書式が揃っていません。多数派に合わせてください。")
        for shape, names in sorted(formats.items(), key=lambda kv: -len(kv[1])):
            print("   %s : %s" % (shape, ", ".join(names)))
        print("   --normalize-list-ids を付けて実行すると、多数派の書式へ揃えます。")
    else:
        print("   listIds の書式は揃っています。")

    print("")
    print("列内部名:")
    for list_name, columns in cfg.get("columnInternalNames", {}).items():
        if not isinstance(columns, dict):
            continue
        unmeasured = [k for k, v in columns.items()
                      if not k.startswith("_") and isinstance(v, str) and v.startswith("<")]
        print("  %-20s : %d列%s" % (list_name, len([k for k in columns if not k.startswith("_")]),
                                     "(未実測: %s)" % ", ".join(unmeasured) if unmeasured else ""))

    features = cfg.get("features", {})
    override = cfg.get("testRecipientOverride", "").strip()
    print("")
    print("機能: errorLogging=%s / eventClose=%s"
          % (features.get("errorLogging"), features.get("eventClose")))
    print("宛先: %s" % ("検証者だけ(testRecipientOverride 設定あり)" if override
                        else "*** 名簿どおり(本番宛先モード) ***"))


def normalize_list_ids(cfg):
    """listIds の書式を、多数派に合わせて揃える。"""
    shapes = {}
    for name, value in cfg.get("listIds", {}).items():
        if name.startswith("_") or not isinstance(value, str):
            continue
        if GUID_PATTERN.match(value):
            shapes.setdefault(value.startswith("{"), []).append(name)
    if len(shapes) < 2:
        return []
    with_braces = len(shapes.get(True, [])) >= len(shapes.get(False, []))
    changed = []
    for name in shapes.get(not with_braces, []):
        body = cfg["listIds"][name].strip("{}")
        cfg["listIds"][name] = ("{%s}" % body) if with_braces else body
        changed.append(name)
    return changed


def write_error_test_copy(cfg, has_bom, source_path, dest_path):
    """メンバー抽出のフィルターだけを壊した設定の写しを書き出す。

    元の設定には触らない。この写しから生成したフローは、対象者を取得する
    GET_Active_Members で必ず失敗し、SCOPE_Catch へ入る。

    個人カードの送信(LOOP_Each_Member)はこの後ろにあるため、**個人宛のカードは
    1通も送られない**。ただし、その手前にある処理は動くので、
    EQ_Events に1行できて、拠点のチャネルへ開始通知が1件投稿される。
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
    broken["columnInternalNames"]["EQ_Config_Members"]["IsActive"] = BROKEN_COLUMN_NAME
    save_config(dest_path, broken, has_bom)
    load_config(dest_path)

    print("")
    print("書き出しました: %s" % dest_path)
    print("  元の %s は変更していません。" % source_path)
    print("")
    print("この写しから生成したフローは、対象者を取得する GET_Active_Members で")
    print("必ず失敗し、SCOPE_Catch へ入ります。")
    print("")
    print("実行すると起きること:")
    print("  - EQ_Events に1行できる(AlertStatus は Open のまま残る)")
    print("  - 拠点のチャネルへ開始通知カードが1件投稿される")
    print("  - 個人宛のカードは1通も送られない(送信処理は失敗箇所より後ろにあるため)")
    print("  - EQ_Received_Items に ProcessingStatus=Error の行が1件増える")
    print("  - フローの実行履歴は赤(失敗)になる")
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
    parser.add_argument("--diagnose", action="store_true",
                        help="設定の書式を点検するだけで、書き換えは行わない")
    parser.add_argument("--normalize-list-ids", action="store_true",
                        help="listIds のGUIDの書式(中かっこの有無)を多数派へ揃える")
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

    if args.diagnose:
        diagnose(cfg, args.config)
        return

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

    # --- 3.5 リストGUIDの書式揃え -------------------------------------------
    if args.normalize_list_ids:
        renamed = normalize_list_ids(cfg)
        if renamed:
            changes.append("listIds の書式を多数派へ揃えました: %s" % ", ".join(renamed))
        else:
            changes.append("listIds の書式はすでに揃っていました(変更なし)")

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
