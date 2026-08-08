"""
Schedule Manager - 夜間バッチのスケジュールをコードから管理する

目的:
    Windowsタスクスケジューラの画面を手作業で触らずに、
    schedule.json の時刻を書き換えるだけでスケジュールを更新する。

方式の選択理由:
    実行そのものはWindowsタスクスケジューラに任せ、その登録・更新だけを
    このスクリプトが schtasks.exe 経由で行う。
    Pythonを常駐させる方式(scheduleライブラリ等)は採用しない。
    再起動・スリープ・プロセス死亡でその夜の実行が丸ごと消え、しかも
    消えたことに気づけないため、無人の深夜実行には信頼性が足りない。

安全設計:
    task_prefix で始まるタスクだけを対象とする。
    他のタスクは列挙も削除もしない。

使い方:
    # 今の登録状況を確認（変更しない）
    python schedule_manager.py --list

    # 実行される schtasks コマンドを確認（変更しない）
    python schedule_manager.py --apply --dry-run

    # schedule.json の内容をWindowsへ反映
    python schedule_manager.py --apply

    # 管理下のタスクをすべて削除
    python schedule_manager.py --remove

バージョンはファイル名ではなくGitで管理する。
"""

import os
import re
import sys
import ntpath
import json
import argparse
import subprocess

DEFAULT_CONFIG = "schedule.json"
TIME_RE = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')
NAME_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


# ============================================================================
# 設定の読み込みと検証
# ============================================================================
def load_config(path):
    """schedule.json を読み、内容を検証して返す。

    ここで弾いておかないと、schtasks に不正な値が渡って
    分かりにくいエラーになるため、先に全部チェックする。
    """
    if not os.path.exists(path):
        raise SystemExit(f"[ERROR] 設定ファイルが見つかりません: {path}")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        raise SystemExit(f"[ERROR] {path} を読めません: {e}")

    prefix = cfg.get('task_prefix')
    if not prefix or not NAME_RE.match(prefix):
        raise SystemExit("[ERROR] task_prefix は英数字・アンダースコア・ハイフンで指定してください")

    working_dir = cfg.get('working_dir') or ''
    tasks = cfg.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        raise SystemExit("[ERROR] tasks が空です")

    seen = set()
    for t in tasks:
        name = t.get('name', '')
        if not NAME_RE.match(name):
            raise SystemExit(f"[ERROR] タスク名が不正です: {name!r}")
        if name in seen:
            raise SystemExit(f"[ERROR] タスク名が重複しています: {name}")
        seen.add(name)

        time_str = t.get('time', '')
        if not TIME_RE.match(time_str):
            raise SystemExit(f"[ERROR] {name}: 時刻は HH:MM (24時間表記) で指定してください: {time_str!r}")

        if not t.get('command'):
            raise SystemExit(f"[ERROR] {name}: command が未指定です")

    return {
        'prefix': prefix,
        'working_dir': working_dir,
        'interactive': bool(cfg.get('interactive', True)),
        'tasks': tasks,
    }


def full_task_name(prefix, name):
    return f"{prefix}_{name}"


def resolve_command(working_dir, command):
    """実行するバッチの絶対パスを返す。

    各バッチは内部で cd /d を行うため、作業ディレクトリの指定は不要。
    絶対パスで指定しておけば、タスクスケジューラの「開始場所」に依存しない。

    パスの連結には ntpath を使う。os.path は実行環境依存で、
    Windows以外で --dry-run したときに区切りが / になってしまい、
    表示されたコマンドをそのまま貼れなくなるため。
    """
    if ntpath.isabs(command) or os.path.isabs(command):
        return command
    if working_dir:
        return ntpath.join(working_dir, command)
    return os.path.abspath(command)


# ============================================================================
# schtasks の呼び出し
# ============================================================================
def run_schtasks(args, dry_run=False, check=True):
    """schtasks.exe を呼ぶ。dry_run のときは実行せずコマンドだけ返す。"""
    cmd = ['schtasks'] + args
    printable = 'schtasks ' + ' '.join(
        (f'"{a}"' if (' ' in a and not a.startswith('"')) else a) for a in args
    )
    if dry_run:
        return 0, printable, ''

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding='cp932', errors='replace')
    except FileNotFoundError:
        raise SystemExit("[ERROR] schtasks.exe が見つかりません。Windowsで実行してください。")

    out = (proc.stdout or '').strip()
    err = (proc.stderr or '').strip()
    if check and proc.returncode != 0:
        print(f"[ERROR] コマンド失敗 (終了コード {proc.returncode}): {printable}")
        if err:
            print(f"        {err}")
        elif out:
            print(f"        {out}")
    return proc.returncode, out, err


def query_managed_tasks(prefix, dry_run=False):
    """現在登録されている、管理対象タスクの一覧を取得する。

    schtasks /Query の出力を解析する。ロケールによって見出しが
    変わるため、タスク名だけは英日どちらの表記でも拾えるようにする。
    """
    if dry_run:
        return {}

    rc, out, _ = run_schtasks(['/Query', '/FO', 'LIST', '/V'], check=False)
    if rc != 0 or not out:
        return {}

    tasks = {}
    current_name = None
    current = {}
    for line in out.splitlines():
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()

        if key in ('TaskName', 'タスク名'):
            if current_name:
                tasks[current_name] = current
            current_name = value.lstrip('\\')
            current = {}
        elif current_name:
            if key in ('Next Run Time', '次回の実行時刻'):
                current['next_run'] = value
            elif key in ('Status', '状態'):
                current['status'] = value
            elif key in ('Task To Run', '実行するタスク'):
                current['action'] = value
            elif key in ('Start Time', '開始時刻'):
                current['start_time'] = value
            elif key in ('Scheduled Task State', 'スケジュールされたタスクの状態'):
                current['state'] = value
    if current_name:
        tasks[current_name] = current

    return {k: v for k, v in tasks.items() if k.startswith(prefix + '_')}


def build_create_args(cfg, task):
    """schtasks /Create に渡す引数列を組み立てる。"""
    tn = full_task_name(cfg['prefix'], task['name'])
    tr = resolve_command(cfg['working_dir'], task['command'])

    # [20260808] バッチへ渡す引数に対応する。
    # command に "x.bat auto" と書くと全体がパスとして扱われてしまうため、
    # 引数は args に分けて指定する。
    extra = (task.get('args') or '').strip()
    tr_value = f'"{tr}" {extra}'.strip() if extra else f'"{tr}"'

    args = [
        '/Create',
        '/TN', tn,
        # パスに空白が含まれるため、値自体を引用符で囲んだ状態で渡す
        '/TR', tr_value,
        '/SC', 'DAILY',
        '/ST', task['time'],
        '/F',                     # 同名タスクがあれば上書き
    ]
    if cfg['interactive']:
        # Chromeの画面操作を伴うため、ログオン中の対話セッションで実行する。
        # これを外すとバックグラウンドセッションで動き、Chromeが正しく
        # 表示されずに失敗しうる。
        user = os.environ.get('USERNAME') or ''
        if user:
            args += ['/RU', user]
        args += ['/IT']
    return args


# ============================================================================
# コマンド
# ============================================================================
def cmd_list(cfg):
    print(f"--- Windows に登録されている {cfg['prefix']}_* タスク ---")
    managed = query_managed_tasks(cfg['prefix'])
    if not managed:
        print("  （登録なし）")
    else:
        for name in sorted(managed):
            info = managed[name]
            print(f"  {name}")
            print(f"      状態    : {info.get('status') or info.get('state') or '不明'}")
            print(f"      次回実行: {info.get('next_run', '不明')}")
            print(f"      実行内容: {info.get('action', '不明')}")

    print()
    print("--- schedule.json の定義 ---")
    for t in cfg['tasks']:
        mark = ' ' if t.get('enabled', True) else '×'
        tn = full_task_name(cfg['prefix'], t['name'])
        state = '登録済' if tn in managed else '未登録'
        note = f"  {t.get('note','')}" if t.get('note') else ''
        print(f"  [{mark}] {t['time']}  {tn:32s} {state}{note}")

    # 定義と実体のズレを明示する（気づけないと意味がない）
    defined = {full_task_name(cfg['prefix'], t['name'])
               for t in cfg['tasks'] if t.get('enabled', True)}
    orphans = set(managed) - defined
    missing = defined - set(managed)
    if orphans or missing:
        print()
        print("--- 差分 ---")
        for o in sorted(orphans):
            print(f"  ! Windows側にのみ存在: {o}  (--apply で削除されます)")
        for m in sorted(missing):
            print(f"  ! 未登録: {m}  (--apply で登録されます)")
    return 0


def cmd_apply(cfg, dry_run):
    managed = query_managed_tasks(cfg['prefix'], dry_run)
    defined = {}
    for t in cfg['tasks']:
        defined[full_task_name(cfg['prefix'], t['name'])] = t

    failures = 0

    # 1) 有効なタスクを作成・更新
    for t in cfg['tasks']:
        tn = full_task_name(cfg['prefix'], t['name'])
        if not t.get('enabled', True):
            continue

        target = resolve_command(cfg['working_dir'], t['command'])
        if not dry_run and not os.path.exists(target):
            print(f"  [SKIP] {tn}: 実行対象が見つかりません → {target}")
            failures += 1
            continue

        rc, printable, _ = run_schtasks(build_create_args(cfg, t), dry_run)
        action = '確認' if dry_run else ('登録' if rc == 0 else '失敗')
        print(f"  [{action}] {t['time']}  {tn}")
        if dry_run:
            print(f"           {printable}")
        elif rc != 0:
            failures += 1

    # 2) 無効化されたタスク・定義から消えたタスクを削除
    #    管理対象プレフィックスのものだけを削除する
    for tn in sorted(managed):
        t = defined.get(tn)
        if t is not None and t.get('enabled', True):
            continue
        rc, printable, _ = run_schtasks(['/Delete', '/TN', tn, '/F'], dry_run)
        action = '確認' if dry_run else ('削除' if rc == 0 else '失敗')
        print(f"  [{action}] {tn}")
        if dry_run:
            print(f"           {printable}")
        elif rc != 0:
            failures += 1

    print()
    if dry_run:
        print("dry-run のため、実際の変更は行っていません。")
        return 0
    if failures:
        print(f"[結果] {failures}件が失敗しました。")
        return 1
    print("[結果] スケジュールを反映しました。--list で確認できます。")
    return 0


def cmd_remove(cfg, dry_run):
    managed = query_managed_tasks(cfg['prefix'], dry_run)
    if not managed and not dry_run:
        print("  削除対象はありません。")
        return 0

    failures = 0
    for tn in sorted(managed):
        rc, printable, _ = run_schtasks(['/Delete', '/TN', tn, '/F'], dry_run)
        action = '確認' if dry_run else ('削除' if rc == 0 else '失敗')
        print(f"  [{action}] {tn}")
        if dry_run:
            print(f"           {printable}")
        elif rc != 0:
            failures += 1
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(
        description="夜間バッチのスケジュールを schedule.json から管理する")
    parser.add_argument('--config', default=DEFAULT_CONFIG)
    parser.add_argument('--dry-run', action='store_true',
                        help='実行せず、発行するコマンドだけ表示する')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--list', action='store_true', help='現在の登録状況を表示する')
    group.add_argument('--apply', action='store_true', help='schedule.json を反映する')
    group.add_argument('--remove', action='store_true', help='管理下のタスクを削除する')
    args = parser.parse_args()

    if sys.platform != 'win32' and not args.dry_run:
        print("[ERROR] このスクリプトはWindows専用です。")
        print("        コマンドの確認だけなら --dry-run を付けてください。")
        return 1

    cfg = load_config(args.config)

    print(f"設定: {args.config} / プレフィックス: {cfg['prefix']}_*")
    print(f"作業フォルダ: {cfg['working_dir']}")
    print()

    if args.apply:
        return cmd_apply(cfg, args.dry_run)
    if args.remove:
        return cmd_remove(cfg, args.dry_run)
    return cmd_list(cfg)


if __name__ == '__main__':
    sys.exit(main())
