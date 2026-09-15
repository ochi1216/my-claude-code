# -*- coding: utf-8 -*-
"""
forecast.py
学びジャーナル - 「読み（予測）」の記録と答え合わせ

画面上は 事実 / 読み / 打ち手 と呼ぶ（空・雨・傘に対応する）。
既存の機能には「読み」の席が無い。LKPTのK/Pは観測した過去、Tは次の行動
なので、三つとも事実か打ち手にあたる。このモジュールは、日付つきの断定
として読みを残し、確認期日が来たら必ず答え合わせを促すためのデータ層を
受け持つ。保存キーは sky / rain / umbrella のままにしてあり（既存の
forecasts.json との互換のため）、呼び名だけが表示側で切り替わっている。

目的は「読みを書くこと」ではなく「後から答え合わせが必ず行われること」。
読みを書き留めていない経験は複利で積まれない（後知恵バイアスにより、人は
後から「そうなると思っていた」と記憶を書き換えるため、記録が無いと自分の
読みが外れたことに気づけない）。外れに気づけないものは上達しない。

保存先を journal_data.xlsx と分けている理由:
  1. まだ形が固まっていないため、列の追加に自己修復マイグレーションが要る
     Excelよりも、後から項目を足しやすいJSONの方が適している
  2. Excelの行番号をIDに使うと、確認期日で並べ替えた瞬間にIDが壊れる
     （Actionsシートが抱えている弱点と同じ）。ここでは本物のIDを持つ
  3. journal_data.xlsx は毎時のタイムログ記録でロック・保存が走る。
     週1本しか増えない資産を、その保存失敗に巻き込まない
  4. 外部プロセス（morning_brief.py 等）からロック無しで読める

これはリスク管理ではない。リスクは10個併記しても誰も困らないが、
Forecastは1つに絞った瞬間に外れが確定する。「選ばされること」と
「後で採点されること」が機能の存在理由なので、そこを緩めると
ただのリスク一覧がもう一つ増えるだけになる。

  リスク管理              Forecast
  起こりうること      →  起きると読むこと
  何個でも併記可      →  1件につき1つ
  ヘッジしてよい      →  断定（外れが確定する形）
  発生しなければ終了  →  必ず答え合わせをする
  案件を守る          →  自分の判断力を測り、鍛える

Tetlock『超予測力』/ Annie Duke『Thinking in Bets』のディシジョン・
ジャーナルが下敷き。この研究群の結論のうち実装に直結するのは
「結果だけを見ても上達しない。理由を書き、理由が外れたのかを
確認した人だけが上達する」という点で、実装上は次の2つに落ちる。

  ・読みの当否と理由の当否を別々に採点する（resolve_forecast）
    読みは当たったが理由は違った＝たまたま当たっただけ、が最も学びが
    大きいので、1つの評価にまとめてはいけない
  ・保存後、事実・読み・理由の本文を書き換えられなくする（FROZEN_FIELDS）
    編集できると後知恵バイアスがそのまま入り、記録の意味が消える。
    訂正は append_note() による追記のみで、元の文言は必ず残る

また、この記録は組織の文書ではなく個人の私的な記録である必要がある
（「11月に間に合わせます」と約束している本人が、公式文書に
「間に合わないと読んでいます」とは書けない。コミットメントと正直な
読みは同じ文書に共存できない）。ローカル保存・非公開は配慮ではなく
成立条件。

Version: 0.2.0
"""

import json
import os
import tempfile
from datetime import datetime, timedelta

from storage import EXCEL_PATH

# journal_data.xlsx と同じフォルダに置く（既知のパスに単独で存在させる）
FORECAST_PATH = os.path.join(os.path.dirname(EXCEL_PATH), "forecasts.json")

SCHEMA_VERSION = 2

# 保存後に書き換えてはいけない項目。
# 「まあそうなると思っていた」と後から書き換えられると、外れが記録に
# 残らなくなり、この機能の目的（自分の読みを測る）が丸ごと失われる。
# 訂正は append_note() で追記し、元の文言は必ず残す。
# 確認期日(check_date)は延期の運用があるため凍結しない。
FROZEN_FIELDS = ("sky", "rain", "reason", "created_at", "domain", "id")

# 3領域。後で「どの領域の読みが当たりやすいか」を見るために区別する
DOMAIN_PROJECT = "プロジェクト"
DOMAIN_PEOPLE = "人・組織"
DOMAIN_TECH = "技術"
DOMAINS = [DOMAIN_PROJECT, DOMAIN_PEOPLE, DOMAIN_TECH]

# 確信度。任意入力（空欄可）。最初から必須にすると入力の心理的コストが
# 上がって書かなくなるため、書きたい時だけ書く。
# confidence_pct は将来のキャリブレーション（「70%と書いたもののうち実際に
# 何割が起きたか」を集計し、自信過剰か過小かを見る）用に器だけ先に用意した
# もの。後から足すとマイグレーションが要るため、空欄のまま持っておく
CONFIDENCE_MAYBE = "たぶん"
CONFIDENCE_LIKELY = "おそらく"
CONFIDENCE_ALMOST = "ほぼ確実"
CONFIDENCE_LEVELS = [CONFIDENCE_MAYBE, CONFIDENCE_LIKELY, CONFIDENCE_ALMOST]

OUTCOME_HIT = "○"
OUTCOME_MISS = "×"
OUTCOME_PARTIAL = "△"
OUTCOMES = [OUTCOME_HIT, OUTCOME_MISS, OUTCOME_PARTIAL]

# 読みの当否と理由の当否は必ず別々に採点する。
# 「読みは当たったが理由は違っていた」＝たまたま当たっただけ、が最も学びが
# 大きいケースで、1つの評価にまとめるとこの機能の価値が半減する
# （結果が当たっていてもモデルは壊れたままなので、次に大きく外す）。
_RESULT_LABELS = {
    (OUTCOME_HIT, OUTCOME_HIT): "読みも理由も当たった",
    (OUTCOME_HIT, OUTCOME_MISS): "たまたま当たった（理由は外れ）",
    (OUTCOME_HIT, OUTCOME_PARTIAL): "当たったが理由は部分的",
    (OUTCOME_MISS, OUTCOME_HIT): "外れたが理由の筋は合っていた",
    (OUTCOME_MISS, OUTCOME_MISS): "読みも理由も外れた",
    (OUTCOME_MISS, OUTCOME_PARTIAL): "外れた（理由は部分的）",
    (OUTCOME_PARTIAL, OUTCOME_HIT): "部分的に当たり、理由は合っていた",
    (OUTCOME_PARTIAL, OUTCOME_MISS): "部分的に当たったが理由は外れ",
    (OUTCOME_PARTIAL, OUTCOME_PARTIAL): "どちらも部分的",
}
LABEL_UNJUDGEABLE = "判定不能"


def describe_result(item: dict) -> str:
    """
    読みの当否と理由の当否の組み合わせを、読める1行にして返す。
    値そのものは2つ別々に保存してあり、これは表示用の導出。
    """
    if item.get("status") == STATUS_UNJUDGEABLE:
        return LABEL_UNJUDGEABLE
    key = (item.get("outcome"), item.get("reason_outcome"))
    return _RESULT_LABELS.get(key, "")


def is_lucky_hit(item: dict) -> bool:
    """
    「たまたま当たった」＝読みは○だが理由は×。
    見つけ次第つぶすべき最重要のケースなので、単独で数えられるようにする。
    """
    return (item.get("outcome") == OUTCOME_HIT
            and item.get("reason_outcome") == OUTCOME_MISS)

STATUS_PENDING = "pending"
STATUS_RESOLVED = "resolved"
STATUS_UNJUDGEABLE = "unjudgeable"

# 督促で一度に見せる上限。溜まった全部を出すと壁になり、「閉じる」が
# 習慣化して仕組みごと無視されるようになるため、古い順に少しずつ出す
MAX_DUE_PROMPT = 3

DATE_FMT = "%Y-%m-%d"
STAMP_FMT = "%Y-%m-%d %H:%M"


def _empty_store() -> dict:
    return {"version": SCHEMA_VERSION, "last_prompted_date": "", "forecasts": []}


def _load(path: str = FORECAST_PATH) -> dict:
    """
    保存ファイルを読み込む。存在しない・壊れている場合は空の状態を返す
    （読み取りが例外で落ちると督促そのものが止まってしまうため）。
    """
    if not os.path.exists(path):
        return _empty_store()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️ {os.path.basename(path)} を読み込めませんでした: {e}")
        return _empty_store()
    if not isinstance(data, dict) or not isinstance(data.get("forecasts"), list):
        print(f"⚠️ {os.path.basename(path)} の形式が想定と異なります。空として扱います。")
        return _empty_store()
    data.setdefault("version", SCHEMA_VERSION)
    data.setdefault("last_prompted_date", "")
    _migrate(data)
    return data


def _migrate(data: dict) -> None:
    """
    古い形式のレコードに、後から足した項目を補う（破壊的な変換はしない）。
    v1では結果が1つの評価(diagnosis)にまとまっていたので、
    分かる範囲で「理由の当否」に読み替える。
    """
    for f in data.get("forecasts", []):
        f.setdefault("notes", [])
        f.setdefault("confidence_pct", None)
        f.setdefault("reason_outcome", None)
        legacy = f.pop("diagnosis", None)
        if f.get("reason_outcome") is None and legacy:
            f["reason_outcome"] = {
                "予測も理由も当たった": OUTCOME_HIT,
                "予測は当たったが理由が違った": OUTCOME_MISS,
            }.get(legacy)
    data["version"] = SCHEMA_VERSION


def _save(data: dict, path: str = FORECAST_PATH) -> bool:
    """
    保存ファイルを書き出す。一時ファイルに書いてから置き換えることで、
    書き込み中に落ちても元のファイルが壊れないようにする
    （単一ファイルに全ての読みが入るため、破損の影響が大きい）。
    """
    directory = os.path.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError as e:
        print(f"❌ {os.path.basename(path)} の保存に失敗しました: {e}")
        return False


def _next_id(forecasts: list, now: datetime) -> str:
    """R-YYYYMMDD-NN 形式のIDを採番する（同じ日の連番）。"""
    prefix = f"R-{now.strftime('%Y%m%d')}-"
    used = [f["id"] for f in forecasts if str(f.get("id", "")).startswith(prefix)]
    return f"{prefix}{len(used) + 1:02d}"


def add_forecast(domain: str, sky: str, rain: str, reason: str,
                  confidence: str = "", check_date: str = "", umbrella: str = "",
                  umbrella_task_created: bool = False, confidence_pct=None,
                  path: str = FORECAST_PATH, now: datetime = None) -> dict:
    """
    読みを1本記録する。

    保存した時点で sky / rain / reason は凍結され、以後どの関数からも
    書き換えられない（FROZEN_FIELDS）。訂正は append_note() で追記する。

    Args:
        domain: DOMAINSのいずれか
        sky: 観測した事実
        rain: 読み（外れが分かる断定形。1件につき1つ）
        reason: なぜそうなると見るのか（最重要項目・必須）
        confidence: CONFIDENCE_LEVELSのいずれか。任意（空欄可）
        check_date: "YYYY-MM-DD"。この日に答え合わせをする
        umbrella: そのとき取る手（任意）
        umbrella_task_created: 打ち手をタスクとしても登録したか
        confidence_pct: 確信度のパーセント。将来のキャリブレーション用に
            器だけ用意してある項目で、今は空のままでよい

    Returns:
        dict: 追加した読み。必須項目が空の場合はNone
    """
    sky, rain, reason = sky.strip(), rain.strip(), reason.strip()
    if not (domain and sky and rain and reason and check_date):
        return None
    if now is None:
        now = datetime.now()

    data = _load(path)
    item = {
        "id": _next_id(data["forecasts"], now),
        "created_at": now.strftime(STAMP_FMT),
        "domain": domain,
        "sky": sky,
        "rain": rain,
        "reason": reason,
        # 任意。空欄のまま運用してよい
        "confidence": confidence or "",
        # 将来のキャリブレーション用に器だけ先に持つ（後から足すと移行が要る）
        "confidence_pct": confidence_pct,
        "check_date": check_date,
        "umbrella": umbrella.strip(),
        "umbrella_task_created": bool(umbrella_task_created),
        "status": STATUS_PENDING,
        # 延期回数は事務データではなく測定値。何度も延期される読みは
        # そもそも反証可能な形で書けていなかった、という学びになる
        "defer_count": 0,
        "original_check_date": check_date,
        "resolved_at": None,
        # 読みの当否と理由の当否は必ず別々に持つ
        "outcome": None,
        "reason_outcome": None,
        "actual": None,
        "learned": None,
        # 訂正・補足はここに追記する。本文は書き換えない
        "notes": [],
    }
    data["forecasts"].append(item)
    if not _save(data, path):
        return None
    print(f"🔮 読みを記録しました → [{item['id']}] {rain}（確認: {check_date}）")
    return item


def get_forecasts(path: str = FORECAST_PATH) -> list:
    """全ての読みを、作成順で返す。"""
    return _load(path)["forecasts"]


def get_forecast(forecast_id: str, path: str = FORECAST_PATH) -> dict:
    """IDで1件返す（無ければNone）。"""
    for f in _load(path)["forecasts"]:
        if f.get("id") == forecast_id:
            return f
    return None


def get_due_forecasts(today: datetime = None, limit: int = MAX_DUE_PROMPT,
                       path: str = FORECAST_PATH) -> list:
    """
    確認期日が来ている未記入の読みを、期日が古い順に返す。
    期日を過ぎたものも含む（記入されるまで出し続けるため）。

    limitで件数を絞るのは、溜まった全件を一度に出すと壁になり、
    仕組みごと無視されるようになるのを避けるため。
    """
    if today is None:
        today = datetime.now()
    today_str = today.strftime(DATE_FMT)

    due = [
        f for f in _load(path)["forecasts"]
        if f.get("status") == STATUS_PENDING
        and str(f.get("check_date", "")) <= today_str
    ]
    due.sort(key=lambda f: (str(f.get("check_date", "")), str(f.get("id", ""))))
    return due[:limit] if limit else due


def count_due(today: datetime = None, path: str = FORECAST_PATH) -> int:
    """確認期日が来ている未記入の読みの総数（表示上限とは別に全件数を数える）。"""
    return len(get_due_forecasts(today=today, limit=0, path=path))


class FrozenFieldError(Exception):
    """凍結項目（事実・読み・理由など）を書き換えようとした時に送出する。"""


def _update(forecast_id: str, path: str, mutate) -> bool:
    """
    指定IDの読みにmutateを適用して保存する内部関数。

    mutateの前後でFROZEN_FIELDSを比較し、1つでも変わっていたら保存せずに
    例外を投げる。「編集する関数を作らない」だけでは、後で誰かが不用意に
    書き換える経路を足せてしまうため、データ層で構造的に止める。
    """
    data = _load(path)
    for f in data["forecasts"]:
        if f.get("id") == forecast_id:
            before = {k: f.get(k) for k in FROZEN_FIELDS}
            mutate(f)
            changed = [k for k in FROZEN_FIELDS if f.get(k) != before[k]]
            if changed:
                # 保存せずに落とす。書き換えを黙って通すくらいなら
                # 機能が壊れて見える方がよい
                raise FrozenFieldError(
                    f"凍結項目は書き換えられません: {', '.join(changed)}"
                    f"（訂正は append_note() で追記してください）"
                )
            return _save(data, path)
    print(f"⚠️ 読みが見つかりませんでした: {forecast_id}")
    return False


def append_note(forecast_id: str, note: str, path: str = FORECAST_PATH,
                 now: datetime = None) -> bool:
    """
    読みに訂正・補足を追記する。

    事実・読み・理由の本文は凍結されているので、後から思い直したことは
    すべてここに時刻つきで積む。元の文言が必ず残るため、
    「まあそうなると思っていた」という書き換えが起こらない。
    """
    note = note.strip()
    if not note:
        return False
    if now is None:
        now = datetime.now()

    def mutate(f):
        f.setdefault("notes", []).append({
            "at": now.strftime(STAMP_FMT),
            "text": note,
        })

    ok = _update(forecast_id, path, mutate)
    if ok:
        print(f"📝 追記しました → [{forecast_id}] {note}")
    return ok


def resolve_forecast(forecast_id: str, outcome: str, reason_outcome: str,
                      actual: str = "", learned: str = "",
                      path: str = FORECAST_PATH, now: datetime = None) -> bool:
    """
    答え合わせの結果を記録する。

    読みの当否と理由の当否を別々に採点するのがこの関数の要点。
    「読みは当たったが理由は違った」＝たまたま当たっただけ、が最も学びの
    大きいケースで、1つの評価にまとめると見えなくなる。

    Args:
        outcome: 読みは当たったか（OUTCOMESのいずれか）
        reason_outcome: 理由は合っていたか（OUTCOMESのいずれか）
        actual: 実際に何が起きたか
        learned: 補足（自由記述）
    """
    if now is None:
        now = datetime.now()

    def mutate(f):
        f["status"] = STATUS_RESOLVED
        f["outcome"] = outcome
        f["reason_outcome"] = reason_outcome
        f["actual"] = actual.strip()
        f["learned"] = learned.strip()
        f["resolved_at"] = now.strftime(STAMP_FMT)

    ok = _update(forecast_id, path, mutate)
    if ok:
        item = get_forecast(forecast_id, path)
        label = describe_result(item) if item else ""
        print(f"✅ 答え合わせを記録しました → [{forecast_id}] "
              f"読み{outcome} / 理由{reason_outcome} … {label}")
        if item and is_lucky_hit(item):
            print("💡 たまたま当たったケースです。結果は当たっていても読み筋は"
                  "外れているので、次に同じ理屈で読むと大きく外します。")
    return ok


def defer_forecast(forecast_id: str, new_check_date: str,
                    path: str = FORECAST_PATH) -> bool:
    """
    まだ判定できない読みの確認期日を先送りする。

    ○×△しか出口が無いと、判定できない読みに対しては嘘をつくか無視するかに
    なり、無視が始まった時点でこの仕組みは終わる。正直な出口として用意する。
    延期回数を数えるのは、何度も延期される読み＝反証可能な形で書けて
    いなかった、という診断そのものが学びになるため。
    """
    def mutate(f):
        f["check_date"] = new_check_date
        f["defer_count"] = int(f.get("defer_count", 0)) + 1

    ok = _update(forecast_id, path, mutate)
    if ok:
        item = get_forecast(forecast_id, path)
        count = item.get("defer_count", 0) if item else 0
        print(f"⏭️ 確認期日を {new_check_date} に延期しました（通算{count}回目）")
        if count >= 3:
            print("💡 3回以上延期しています。この読みは反証可能な形になっていない"
                  "可能性があります（それ自体が学びです）。")
    return ok


def mark_unjudgeable(forecast_id: str, note: str = "",
                      path: str = FORECAST_PATH, now: datetime = None) -> bool:
    """
    前提が消えた（案件中止など）ために判定できなくなった読みを終了させる。
    失敗ではない終了。ただし多い場合は「観測可能な結果に紐づけずに
    読みを書く癖がある」という診断になる。
    """
    if now is None:
        now = datetime.now()

    def mutate(f):
        f["status"] = STATUS_UNJUDGEABLE
        f["actual"] = note.strip()
        f["resolved_at"] = now.strftime(STAMP_FMT)

    ok = _update(forecast_id, path, mutate)
    if ok:
        print(f"⛔ 判定不能として終了しました → [{forecast_id}]")
    return ok


def should_prompt_today(today: datetime = None, path: str = FORECAST_PATH) -> bool:
    """
    今日まだ督促を出していなくて、かつ期日の来た読みがあるならTrue。
    毎時のポップアップに混ぜると1日11回になり確実に無視されるため、
    1日1回に抑える。
    """
    if today is None:
        today = datetime.now()
    data = _load(path)
    if data.get("last_prompted_date") == today.strftime(DATE_FMT):
        return False
    return count_due(today=today, path=path) > 0


def mark_prompted_today(today: datetime = None, path: str = FORECAST_PATH) -> bool:
    """今日の督促を出したことを記録する。"""
    if today is None:
        today = datetime.now()
    data = _load(path)
    data["last_prompted_date"] = today.strftime(DATE_FMT)
    return _save(data, path)


# 削除関数は意図的に用意していない。
# 外した読みの記録こそが資産で、消せるようにすると当たったものだけが
# 残り、自分の読みを測るという目的が果たせなくなる。
# 判定できなくなった読みは mark_unjudgeable() で終了させる（記録は残る）。


def suggest_check_date(months: int, today: datetime = None) -> str:
    """
    「+1ヶ月」等のボタン用に確認期日の候補を返す。
    確認期日はこの仕組み全体を回す要なので、入力の手間を減らす。
    """
    if today is None:
        today = datetime.now()
    month = today.month - 1 + months
    year = today.year + month // 12
    month = month % 12 + 1
    # 月末の日付を繰り上げない（1/31 の 1ヶ月後は 2/28 とする）
    day = today.day
    while day > 0:
        try:
            return datetime(year, month, day).strftime(DATE_FMT)
        except ValueError:
            day -= 1
    return today.strftime(DATE_FMT)


if __name__ == "__main__":
    print(f"🔧 forecast.py 単体動作確認 / 保存先: {FORECAST_PATH}")
    items = get_forecasts()
    print(f"  記録済みの読み: {len(items)}件")
    print(f"  確認期日が来ているもの: {count_due()}件")
    for f in get_due_forecasts():
        print(f"   ・[{f['id']}] {f['rain']}（{f['check_date']}）")
