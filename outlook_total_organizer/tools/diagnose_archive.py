"""
オンラインアーカイブ検出・データ取得の診断用スタンドアロンスクリプト。

outlook_total_organizer本体(outlook_total_organizer_20260729_06.py)は一切変更せず、
実際のOutlook環境で「オンラインアーカイブがどう見えているか」「本体と同じ判定ロジックで
実際に検出できるか」「検出できた場合、過去の月のメールが実際に何件あるか」を直接確認する。

【使い方】
Outlookを起動した状態で、このファイル単体をコマンドプロンプトから実行する。
    python diagnose_archive.py
(本体と同じ pywin32 が必要。仮想環境を使っている場合はそちらを有効化してから実行)

【診断の流れ】
STEP 1: namespace.Stores を列挙し、各ストアの DisplayName / ExchangeStoreType を表示。
        本体の _find_online_archive_root() とまったく同じ判定条件で、
        どのストアが「オンラインアーカイブ」と判定されるかを表示する。
STEP 2: 検出されたアーカイブストアのルート直下のフォルダ名を一覧表示し、
        本体が探している「受信トレイ」「送信済みアイテム」の候補名と一致するか確認する。
STEP 3: 過去6か月分、アーカイブ側の月ごとのアイテム件数を表示する。
STEP 4: 比較用に、既定ストア(現行メールボックス)側の同じ月の件数も表示する。

このスクリプトの出力(特にSTEP 1のDisplayName一覧、STEP 2のフォルダ名一覧)を
そのまま共有していただければ、本体側の検出ロジックのどこがずれているか特定できる。
"""
import win32com.client
import pythoncom
from datetime import datetime


def month_range(n_months: int):
    """当月を含め、過去n_months分の(年,月)タプルを古い順で返す。"""
    now = datetime.now()
    y, m = now.year, now.month
    months = []
    for _ in range(n_months):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months.reverse()
    return months


def count_items_in_month(folder, year: int, month: int, date_field: str = "ReceivedTime"):
    """指定フォルダの、指定した暦月内の件数を返す(本体のget_review_mails_for_monthと
    まったく同じRestrict条件)。date_fieldで[ReceivedTime]/[SentOn]を切り替えられるようにした
    (送信済みアイテムはReceivedTimeが正しく設定されていないことがある、というOutlook COMの
    既知の癖を切り分けるため)。フォルダがNone、またはエラーの場合はエラー文字列を返す。"""
    if folder is None:
        return "フォルダ未検出"
    month_start = datetime(year, month, 1)
    month_end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    start_str = month_start.strftime("%m/%d/%Y")
    end_str = month_end.strftime("%m/%d/%Y")
    try:
        items = folder.Items
        items.Sort(f"[{date_field}]", True)
        restricted = items.Restrict(f"[{date_field}] >= '{start_str}' AND [{date_field}] < '{end_str}'")
        return f"{restricted.Count}件"
    except Exception as e:
        return f"エラー({e})"


def print_folder_date_span(folder, label: str, date_field: str = "ReceivedTime"):
    """フォルダ全体を対象に、date_field昇順/降順それぞれで先頭1件を取得し、
    「そのフォルダに入っている最も古い/最も新しいアイテムの日付」を表示する。
    大きなフォルダ(アーカイブ内の"アーカイブ"フォルダ等)が実際にどの期間を
    カバーしているのかを、月単位のRestrictを使わずに素早く確認するための診断。"""
    if folder is None:
        print(f"  [{label}] フォルダ未検出")
        return
    try:
        total = folder.Items.Count
    except Exception as e:
        print(f"  [{label}] 件数取得エラー: {e}")
        return
    print(f"  [{label}] 総アイテム数={total}")
    if total == 0:
        return
    try:
        items_asc = folder.Items
        items_asc.Sort(f"[{date_field}]", False)  # 昇順=最も古いものが先頭
        oldest = items_asc.GetFirst()
        if oldest:
            print(f"    最も古い: {getattr(oldest, 'Subject', '')!r:35} {date_field}={getattr(oldest, date_field, None)}")
    except Exception as e:
        print(f"    最古アイテム取得エラー: {e}")
    try:
        items_desc = folder.Items
        items_desc.Sort(f"[{date_field}]", True)  # 降順=最も新しいものが先頭
        newest = items_desc.GetFirst()
        if newest:
            print(f"    最も新しい: {getattr(newest, 'Subject', '')!r:35} {date_field}={getattr(newest, date_field, None)}")
    except Exception as e:
        print(f"    最新アイテム取得エラー: {e}")


def print_date_field_sample(folder, label: str, sample_n: int = 5):
    """フォルダ内の先頭数件について、ReceivedTime/SentOn/CreationTimeを実際に表示する。
    送信済みアイテムでReceivedTimeが信用できるかどうかを直接目で確認するための診断。"""
    if folder is None:
        print(f"  [{label}] フォルダ未検出")
        return
    print(f"  [{label}] 件名 / ReceivedTime / SentOn / CreationTime (先頭{sample_n}件、Sort無し=フォルダ内の格納順)")
    try:
        items = folder.Items
        count = 0
        for item in items:
            if count >= sample_n:
                break
            try:
                subject = (getattr(item, 'Subject', '') or '')[:30]
                received = getattr(item, 'ReceivedTime', None)
                sent_on = getattr(item, 'SentOn', None)
                created = getattr(item, 'CreationTime', None)
                print(f"    - {subject!r:35} ReceivedTime={received}  SentOn={sent_on}  CreationTime={created}")
            except Exception as e:
                print(f"    - (アイテム読み取りエラー: {e})")
            count += 1
        if count == 0:
            print("    (アイテムが0件でした)")
    except Exception as e:
        print(f"  [{label}] フォルダ読み取りエラー: {e}")


def main():
    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")

        print("=" * 78)
        print("[STEP 1] namespace.Stores 一覧 と、本体と同じロジックでのアーカイブ判定")
        print("=" * 78)
        try:
            default_store_id = namespace.GetDefaultFolder(6).Store.StoreID
        except Exception as e:
            default_store_id = None
            print(f"  (既定ストアIDの取得に失敗: {e})")

        archive_name_patterns = ["オンライン アーカイブ", "online archive", "in-place archive", "archive -"]
        archive_store = None
        other_archive_type_stores = []  # ExchangeStoreType==3だが名前パターンに一致しなかったストア(参考確認用)

        stores = namespace.Stores
        print(f"検出されたストア数: {stores.Count}")
        for i in range(1, stores.Count + 1):
            try:
                store = stores.Item(i)
            except Exception as e:
                print(f"  [{i}] Item取得エラー: {e}")
                continue
            try:
                display_name = store.DisplayName
            except Exception:
                display_name = "(取得不可)"
            try:
                store_id = store.StoreID
            except Exception:
                store_id = None
            try:
                exch_type = store.ExchangeStoreType
            except Exception:
                exch_type = None

            is_default = (default_store_id is not None and store_id == default_store_id)

            print(f"\n  [{i}] DisplayName = {display_name!r}")
            print(f"       ExchangeStoreType = {exch_type}  (0=Mailbox, 1=PublicFolder, 2=NotExchange, 3=ArchiveMailbox, None=取得不可)")
            print(f"       IsDefaultStore    = {is_default}")

            name_lower = (display_name or "").lower()
            matched_by_type = (not is_default) and (exch_type is not None) and (int(exch_type) == 3)
            matched_by_name = (not is_default) and any(p in name_lower for p in archive_name_patterns)
            print(f"       -> ExchangeStoreType==3 で一致: {matched_by_type}")
            print(f"       -> 名前パターンで一致         : {matched_by_name}")

            if (matched_by_type or matched_by_name) and archive_store is None:
                archive_store = store
                print("       ==> ★このストアが「オンラインアーカイブ」として検出されます(本体もこれを使う)")
            elif matched_by_type and not matched_by_name:
                other_archive_type_stores.append((display_name, store))

        if not archive_store:
            print("\n" + "!" * 78)
            print("[結果] オンラインアーカイブとして検出されたストアはありませんでした。")
            print("       本体側の _find_online_archive_root() もNoneを返すため、")
            print("       アーカイブからのメール・予定表取得は一切行われていません。")
            print("       上の一覧に、実際のアーカイブに相当するストアがあるか確認してください。")
            print("       表示されているのにどちらの条件にも一致しない場合、そのDisplayNameを")
            print("       教えていただければ判定ロジックを調整します。")
            print("!" * 78)
            return

        print("\n" + "=" * 78)
        print("[STEP 2] アーカイブストア配下の直下フォルダ一覧")
        print("=" * 78)
        root = archive_store.GetRootFolder()
        print(f"ルートフォルダ名: {root.Name!r}")

        inbox_candidates = ["受信トレイ", "Inbox"]
        sent_candidates = ["送信済みアイテム", "Sent Items"]
        found_inbox = None
        found_sent = None
        try:
            for f in root.Folders:
                marker = ""
                if f.Name in inbox_candidates:
                    marker = "  <- 受信トレイ候補として一致"
                    found_inbox = f
                elif f.Name in sent_candidates:
                    marker = "  <- 送信済み候補として一致"
                    found_sent = f
                try:
                    count = f.Items.Count
                except Exception:
                    count = "?"
                print(f"  - {f.Name!r} (直下アイテム数: {count}){marker}")
        except Exception as e:
            print(f"  フォルダ列挙エラー: {e}")

        if not found_inbox:
            print(f"\n[結果] 受信トレイに相当するフォルダが候補名{inbox_candidates}のいずれとも一致しませんでした。")
            print("       上の一覧の実際のフォルダ名を教えてください。")
        if not found_sent:
            print(f"\n[結果] 送信済みアイテムに相当するフォルダが候補名{sent_candidates}のいずれとも一致しませんでした。")

        months = month_range(6)

        print("\n" + "=" * 78)
        print("[STEP 3] 過去6か月、アーカイブ側の月ごとのアイテム件数")
        print("=" * 78)
        for (yy, mm) in months:
            inbox_count = count_items_in_month(found_inbox, yy, mm)
            sent_count = count_items_in_month(found_sent, yy, mm)
            print(f"  {yy}年{mm:2d}月: 受信(アーカイブ)={inbox_count} / 送信(アーカイブ)={sent_count}")

        print("\n" + "=" * 78)
        print("[STEP 4] 比較: 既定ストア(現行メールボックス)側の同じ月の件数")
        print("=" * 78)
        default_inbox = namespace.GetDefaultFolder(6)
        default_sent = namespace.GetDefaultFolder(5)
        for (yy, mm) in months:
            inbox_count = count_items_in_month(default_inbox, yy, mm)
            sent_count = count_items_in_month(default_sent, yy, mm)
            print(f"  {yy}年{mm:2d}月: 受信(現行)={inbox_count} / 送信(現行)={sent_count}")

        print("\n" + "=" * 78)
        print("[STEP 5] 送信済みアイテムの件数を [SentOn] 基準でも数え直す")
        print("=" * 78)
        print("(Outlookの送信済みアイテムは[ReceivedTime]が正しく設定されていないことがある、")
        print(" という既知の癖があるため、本体が使っている[ReceivedTime]基準と比較する)")
        for (yy, mm) in months:
            recv = count_items_in_month(default_sent, yy, mm, date_field="ReceivedTime")
            sent = count_items_in_month(default_sent, yy, mm, date_field="SentOn")
            print(f"  {yy}年{mm:2d}月: 送信(現行) ReceivedTime基準={recv} / SentOn基準={sent}")

        print("\n" + "=" * 78)
        print("[STEP 6] 送信済みアイテムの日時フィールドを実際にサンプル表示")
        print("=" * 78)
        print_date_field_sample(default_sent, "送信済み(現行)")
        if found_sent:
            print_date_field_sample(found_sent, "送信済み(アーカイブ)")

        print("\n" + "=" * 78)
        print("[STEP 7] アーカイブ内の「アーカイブ」フォルダ(10825件)が実際にカバーしている期間")
        print("=" * 78)
        print("(「受信トレイ」「送信済みアイテム」より遥かに件数が多い別フォルダ。")
        print(" 過去のOutlook設定で使われていた汎用の自動整理先である可能性があるため確認する)")
        try:
            archive_bulk_folder = None
            for f in root.Folders:
                if f.Name == "アーカイブ":
                    archive_bulk_folder = f
                    break
        except Exception as e:
            archive_bulk_folder = None
            print(f"  フォルダ取得エラー: {e}")
        print_folder_date_span(archive_bulk_folder, "アーカイブ(汎用フォルダ)")

        print("\n" + "=" * 78)
        print("[STEP 8] 参考: ExchangeStoreType==3だが名前パターンに一致しなかったストア")
        print("=" * 78)
        print("(本体はこれらを「オンラインアーカイブ」として使わないが、2023_Q3/2023_Q4等の")
        print(" 手動PSTアーカイブが実は直近データも含んでいないか、念のため確認する)")
        if not other_archive_type_stores:
            print("  該当するストアはありませんでした。")
        for name, store in other_archive_type_stores:
            try:
                store_root = store.GetRootFolder()
                print(f"\n  ストア: {name!r}")
                for f in store_root.Folders:
                    try:
                        cnt = f.Items.Count
                    except Exception:
                        cnt = "?"
                    print(f"    - {f.Name!r} (アイテム数: {cnt})")
                    if f.Name in ("受信トレイ", "Inbox", "送信済みアイテム", "Sent Items"):
                        print_folder_date_span(f, f"{name} / {f.Name}")
            except Exception as e:
                print(f"  ストア{name!r}の読み取りエラー: {e}")

        print("\n" + "=" * 78)
        print("[STEP 9] 現行メールボックス側の直下フォルダ一覧(手動「アーカイブ」ボタンの")
        print("         移動先を確認する。この組織のOutlookでは、リボンの「アーカイブ」")
        print("         ボタンの移動先が「アーカイブ」でも「Archive」でもなく")
        print("         「Go2Archive」という独自名のフォルダになっていることが判明したため、")
        print("         候補名にGo2Archiveを追加した)")
        print("=" * 78)
        archive_folder_candidates = ("アーカイブ", "Archive", "Go2Archive")
        try:
            default_root = namespace.GetDefaultFolder(6).Parent  # Inboxの親 = 現行ストアのルート
            print(f"現行ストアのルートフォルダ名: {default_root.Name!r}")
            default_archive_folders = []
            for f in default_root.Folders:
                try:
                    cnt = f.Items.Count
                except Exception:
                    cnt = "?"
                marker = ""
                if f.Name in archive_folder_candidates:
                    marker = "  <- 「アーカイブ」ボタンの移動先候補"
                    default_archive_folders.append(f)
                print(f"  - {f.Name!r} (直下アイテム数: {cnt}){marker}")
            if default_archive_folders:
                for af in default_archive_folders:
                    print()
                    print_folder_date_span(af, f"{af.Name}(現行メールボックス側)")
                    print()
                    for (yy, mm) in months:
                        cnt = count_items_in_month(af, yy, mm, date_field="ReceivedTime")
                        print(f"  {yy}年{mm:2d}月: {af.Name}(現行)={cnt}")
            else:
                print(f"\n  現行メールボックス側に{archive_folder_candidates}という名前のフォルダは")
                print("  見つかりませんでした。上の一覧の実際のフォルダ名を教えてください。")
        except Exception as e:
            print(f"  現行ストアのフォルダ列挙エラー: {e}")

        print("\n診断完了。")
        print("・STEP3で2か月より前の月がすべて0 → アーカイブ側の日時条件、または")
        print("  アーカイブにその時期のデータがまだ移動されていない可能性")
        print("・STEP4で受信は件数があるのに送信が0の月がある → STEP5でSentOn基準との差を確認")
        print("  (ReceivedTime基準とSentOn基準で件数が大きく異なる場合、本体側の")
        print("  get_review_mails_for_monthが送信済みアイテムにも[ReceivedTime]を使っているのが")
        print("  原因の可能性が高い)")
        print("・STEP6で実際のReceivedTime/SentOnの値を見比べ、送信済みアイテムのReceivedTimeが")
        print("  SentOnと大きくズレている(または空)かどうかを直接確認できます")

    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
