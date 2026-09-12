# -*- coding: utf-8 -*-
"""Enoviaログインの失敗を、原因ごとに切り分けて伝える（v20260911_02）

【きっかけ】自宅からVPN未接続でログインを試したところ、実際の原因は
DNS解決の失敗（ERR_NAME_NOT_RESOLVED）だったのに、画面には
「Edgeの起動に失敗しました」と表示された。Edgeは正常に起動しており、
案内された対処（enovia_auth_mode を manual にする）も的外れだった。

原因は、ブラウザの起動と、開いた後の接続を**1つの try でまとめて**
捕まえていたこと。原因の違う失敗を同じ文面で案内していた。

ネットワークにもブラウザにもアクセスしない。
実行: python tests/test_23_login_error_messages.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, Checker  # noqa: E402

check = Checker()

BASE = "https://dspace.plm.nexperia.com/3dspace"


def message_for(error_text):
    return dsm._enovia_navigation_error_message(BASE, RuntimeError(error_text))


# ── H1 実際に発生した事例 ────────────────────────────────────
print("\n[H1] 実際に発生した事例（自宅・VPN未接続）")
real = ("Page.goto: net::ERR_NAME_NOT_RESOLVED at "
        "https://dspace.plm.nexperia.com/3dspace\n"
        'Call log:\n  - navigating to "https://dspace.plm.nexperia.com/3dspace"')
text = message_for(real)
check("原因コードを示す", "ERR_NAME_NOT_RESOLVED" in text, text)
check("DNSの問題だと伝える", "DNS" in text, text)
check("VPNの可能性を挙げる", "VPN" in text, text)
check("切り分けの手順（nslookup）を示す",
      "nslookup dspace.plm.nexperia.com" in text, text)
check("対象URLを示す", BASE in text)
check("★Edgeの起動を疑わせない（今回の誤案内）",
      "Edgeの起動に失敗" not in text, text)
check("★manualへの切り替えを勧めない（的外れな対処）",
      "enovia_auth_mode" not in text, text)


# ── H2 他の原因も取り違えないこと ────────────────────────────
print("\n[H2] 原因ごとの案内")
for code, must_have in [
    ("net::ERR_CONNECTION_TIMED_OUT", "タイムアウト"),
    ("net::ERR_CONNECTION_REFUSED", "拒否"),
    ("net::ERR_CERT_AUTHORITY_INVALID", "証明書"),
    ("net::ERR_INTERNET_DISCONNECTED", "ネットワークに接続されていません"),
    ("net::ERR_PROXY_CONNECTION_FAILED", "プロキシ"),
]:
    text = message_for(code)
    check(f"{code} を正しく分類する", must_have in text, text)
    check(f"{code} でもEdgeの起動を疑わせない",
          "Edgeの起動に失敗" not in text)

unknown = message_for("Page.goto: something completely unexpected happened")
check("知らないエラーは、分類せずに原文を見せる",
      "something completely unexpected" in unknown, unknown)
check("知らないエラーでも対象URLは示す", BASE in unknown)
check("知らないエラーでも決めつけない",
      "DNS" not in unknown and "VPN" not in unknown, unknown)


# ── H3 起動失敗は、従来どおりEdgeの案内をする ────────────────
print("\n[H3] ブラウザ自体を起動できなかった場合")
launch = dsm._enovia_launch_error_message(RuntimeError("Executable doesn't exist"))
check("起動失敗はEdgeの問題として案内する", "Edgeを起動できませんでした" in launch, launch)
check("manualへの切り替えを案内する（この場合は適切）",
      "enovia_auth_mode" in launch and "manual" in launch, launch)
check("元のエラーも残す", "Executable doesn't exist" in launch)


# ── H4 実装の構造 ────────────────────────────────────────────
print("\n[H4] 実装の構造（まとめて捕まえていないか）")
source = Path(dsm.__file__).read_text(encoding="utf-8")
check("起動と接続を別々に扱っている",
      "_enovia_launch_error_message(e)" in source
      and "_enovia_navigation_error_message(base_url, e)" in source)
check("接続に失敗したらCookie収集へ進まない",
      "if nav_error is None:" in source)
check("接続の失敗をそのまま返している", "if nav_error:" in source)
check("従来の一括メッセージが残っていない",
      'f"Edgeの起動に失敗しました: {e}' not in source)

check.finish()
