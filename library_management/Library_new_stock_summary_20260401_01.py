r"""
CHANGELOG_Library_new_stock_summary.mdに移管
"""

import re
import os
import time
import datetime
import requests
from bs4 import BeautifulSoup
import tkinter as tk
import webbrowser
import json
import tkinter.messagebox as messagebox
import urllib.parse

# ==========================================
# 定数・設定値（ここからコピー）
# ==========================================
BASE_URL = "https://www.kyotocitylib.jp"
TOP_URL = f"{BASE_URL}/winj/opac/newly.do?lang=ja"

# 出力先ディレクトリ
OUTPUT_DIR = r"C:\Users\nx023836\Nexperia\My Private - Documents\Summary"

# 履歴保存用ファイルのパス（OUTPUT_DIR内に作成）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(SCRIPT_DIR, "category_history.json")

# ブラウザとして認識させるためのヘッダー
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
}

WAIT_TIME = 1.0  # アクセス間隔（秒）
MAX_PAGES_PER_CATEGORY = 30  # 1カテゴリあたりの最大取得ページ数
# ==========================================


def select_categories_ui(categories, history):
    """Tkinterを使用して分類を選択するGUIを表示する（一括トグルボタン追加版）"""
    root = tk.Tk()
    root.title("抽出したい分類を選択してください")
    root.geometry("550x630")

    vars_list = []

    # トグル状態管理変数
    is_all_checked = [True]

    def toggle_all():
        is_all_checked[0] = not is_all_checked[0]
        toggle_btn.config(text="すべて選択解除" if is_all_checked[0] else "すべて選択")
        only_new_var.set(is_all_checked[0])
        for v in vars_list:
            v.set(is_all_checked[0])

    # --- 全選択/解除トグルボタンの追加 ---
    btn_frame = tk.Frame(root)
    btn_frame.pack(side="top", fill="x", padx=20, pady=(10, 0))
    toggle_btn = tk.Button(btn_frame, text="すべて選択解除", command=toggle_all, width=15, cursor="hand2")
    toggle_btn.pack(anchor="w")

    # --- 新着のみ抽出チェックボックスの追加 ---
    top_frame = tk.Frame(root)
    top_frame.pack(side="top", fill="x", padx=20, pady=5)
    # デフォルトをON(True)に変更
    only_new_var = tk.BooleanVar(value=True)
    tk.Checkbutton(top_frame, text="新着のみ抽出（過去に取得した本を除外）", variable=only_new_var, font=("", 10, "bold")).pack(anchor="w")

    # スクロールバー付きのメインエリア設定
    canvas = tk.Canvas(root)
    scrollbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    # --- ヘッダー行の追加 (Gridレイアウト) ---
    tk.Label(scrollable_frame, text="分類", font=("", 10, "bold")).grid(row=0, column=0, sticky="w", padx=20, pady=5)
    tk.Label(scrollable_frame, text="前回", font=("", 10, "bold")).grid(row=0, column=1, padx=10, pady=5)
    tk.Label(scrollable_frame, text="最新", font=("", 10, "bold")).grid(row=0, column=2, padx=10, pady=5)
    tk.Label(scrollable_frame, text="差分", font=("", 10, "bold")).grid(row=0, column=3, padx=10, pady=5)
    tk.Label(scrollable_frame, text="新着", font=("", 10, "bold")).grid(row=0, column=4, padx=10, pady=5)

    today_str = datetime.date.today().isoformat()

    # リスト項目の生成
    for i, cat in enumerate(categories):
        row_idx = i + 1
        # デフォルトをON(True)に変更
        var = tk.BooleanVar(value=True)
        vars_list.append(var)

        cat_name = cat['name']
        if cat_name in history:
            h_data = history[cat_name]
            last_date = h_data.get("last_update_date", "1970-01-01")

            if last_date == today_str:
                # 本日更新済み
                prev_val = h_data.get("prev_count", 0)
                latest_val = h_data.get("latest_count", 0)
                diff_val = latest_val - prev_val

                prev_str = str(prev_val)
                latest_str = str(latest_val)
                if diff_val > 0:
                    diff_str = f"+{diff_val}"
                    diff_color = "red"
                elif diff_val < 0:
                    diff_str = str(diff_val)
                    diff_color = "blue"
                else:
                    diff_str = "0"
                    diff_color = "black"

                new_books_val = h_data.get("new_books_count", 0)
                new_books_str = str(new_books_val)
                new_books_color = "red" if new_books_val > 0 else "black"
            else:
                # 本日未更新（最新と差分を「-」で明示）
                prev_val = h_data.get("latest_count", 0)
                prev_str = str(prev_val)
                latest_str = "-"
                diff_str = "-"
                diff_color = "black"
                new_books_str = "-"
                new_books_color = "black"
        else:
            # 完全に新規
            prev_str = "-"
            latest_str = "-"
            diff_str = "-"
            diff_color = "black"
            new_books_str = "-"
            new_books_color = "black"

        cb = tk.Checkbutton(scrollable_frame, text=cat_name, variable=var, anchor="w")
        cb.grid(row=row_idx, column=0, sticky="w", padx=20, pady=2)

        tk.Label(scrollable_frame, text=prev_str).grid(row=row_idx, column=1, padx=10, pady=2)
        tk.Label(scrollable_frame, text=latest_str).grid(row=row_idx, column=2, padx=10, pady=2)
        tk.Label(scrollable_frame, text=diff_str, fg=diff_color).grid(row=row_idx, column=3, padx=10, pady=2)
        tk.Label(scrollable_frame, text=new_books_str, fg=new_books_color).grid(row=row_idx, column=4, padx=10, pady=2)

    # --- レイアウト配置の修正とフィルタバリデーション ---
    selected_indices = []
    filter_start = None
    filter_end = None
    is_cancelled = [True]

    def parse_ym(text):
        """文字列(yyyy.m)を整数(yyyyMM)に変換する。エラー時はValueErrorを投げる"""
        text = text.strip()
        if not text:
            return None
        match = re.fullmatch(r'(\d{4})\.(\d{1,2})', text)
        if not match:
            raise ValueError("format")
        y, m = int(match.group(1)), int(match.group(2))
        if m < 1 or m > 12:
            raise ValueError("month")
        return y * 100 + m

    def on_submit():
        nonlocal selected_indices, filter_start, filter_end

        s_text = start_entry.get()
        e_text = end_entry.get()

        # 入力値の検証
        try:
            s_val = parse_ym(s_text)
            e_val = parse_ym(e_text)
        except ValueError:
            messagebox.showwarning("入力エラー", "年月は yyyy.m または yyyy.mm の形式で入力してください（例: 2026.1）")
            return

        # 論理的矛盾の検証
        if s_val is not None and e_val is not None and s_val > e_val:
            messagebox.showwarning("入力エラー", "開始年月は終了年月以前に指定してください。")
            return

        filter_start = s_val
        filter_end = e_val
        selected_indices = [i for i, v in enumerate(vars_list) if v.get()]
        is_cancelled[0] = False
        root.destroy()

    # 1. 抽出開始ボタンを「最下部」にパッキング
    btn = tk.Button(root, text="抽出開始", command=on_submit, bg="#0056b3", fg="white", height=2)
    btn.pack(side="bottom", fill="x", padx=20, pady=10)

    # 2. ボタンの直上にフィルタUIを配置
    filter_frame = tk.Frame(root)
    filter_frame.pack(side="bottom", fill="x", padx=20, pady=5)

    tk.Label(filter_frame, text="出版年月フィルタ (yyyy.m形式、空欄で全件):").grid(row=0, column=0, columnspan=4, sticky="w")
    tk.Label(filter_frame, text="開始:").grid(row=1, column=0, sticky="e")
    start_entry = tk.Entry(filter_frame, width=10)
    start_entry.grid(row=1, column=1, padx=5)

    tk.Label(filter_frame, text="～ 終了:").grid(row=1, column=2, sticky="e")
    end_entry = tk.Entry(filter_frame, width=10)
    end_entry.grid(row=1, column=3, padx=5)

    # 3. 残りの上部スペースをスクロールエリアに割り当てる
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    def on_closing():
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

    if is_cancelled[0]:
        return None, None, None, None
    return [categories[i] for i in selected_indices], filter_start, filter_end, only_new_var.get()

def setup_directory():
    """出力先ディレクトリが存在しない場合は作成する"""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"[INFO] 出力ディレクトリを作成しました: {OUTPUT_DIR}")


def fetch_category_links(session):
    """新着図書トップページからリスト構造(ol/li)を解析して名称、URL、冊数を取得する"""
    print(f"[INFO] トップページへアクセス中: {TOP_URL}")
    response = session.get(TOP_URL, headers=HEADERS)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")

    categories = []
    # 証拠画像 image_82917e.jpg に基づくセレクタ
    list_container = soup.find("ol", class_=lambda x: x and "list-tag" in x)
    if not list_container:
        print("[ERROR] カテゴリリスト(ol.list-tag)が見つかりません。サイト構造が変更された可能性があります。")
        return []

    items = list_container.find_all("li", recursive=False)
    print("[INFO] 冊数情報の解析を開始します...")

    for li in items:
        # 1. カテゴリ名とURLの抽出 (div.tag-name 内の aタグ)
        tag_name_div = li.find("div", class_="tag-name")
        if not tag_name_div:
            continue
        link_tag = tag_name_div.find("a", href=True)
        if not link_tag:
            continue

        name = link_tag.get_text(strip=True)
        url = BASE_URL + link_tag["href"]

        # 2. 冊数情報の抽出 (div.info 内の p.num.bold)
        count_num = 0
        count_str = ""
        info_div = li.find("div", class_="info")
        if info_div:
            num_p = info_div.find("p", class_=lambda x: x and "num" in x)
            if num_p:
                num_text = num_p.get_text(strip=True)
                match = re.search(r'(\d+)', num_text)
                if match:
                    count_num = int(match.group(1))
                    count_str = f"({count_num}冊)"

        categories.append({
            "name": name,
            "url": url,
            "count_str": count_str,
            "count_num": count_num
        })
        print(f"  - {name.ljust(15)} : {count_num}冊")

    print(f"[INFO] 合計 {len(categories)}個の分類を取得しました。")
    return categories


def fetch_books_from_category(session, category_url):
    """
    分類のURLから書籍一覧を取得し、次ページがあれば辿って全件取得する。（最大ページ数は定数に依存）
    抽出時に改行や連続空白のサニタイズを行い、検索バグを防止する。
    """
    books = []
    current_url = category_url
    page_count = 0

    while current_url and page_count < MAX_PAGES_PER_CATEGORY:
        page_count += 1
        print(f"[INFO] 分類ページ( {page_count}ページ目 )へアクセス中: {current_url}")
        response = session.get(current_url, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        # 書籍情報の抽出
        reports = soup.find_all("div", class_="report")
        for report in reports:
            link_tag = report.find("a", href=lambda href: href and "switch-detail.do" in href)
            if not link_tag:
                continue

            title_span = link_tag.find("span", class_="title")
            raw_title = title_span.get_text(strip=True) if title_span else link_tag.get_text(strip=True)
            # 改行(\n)やタブ、連続する全角/半角空白を1つの半角スペースに変換し、両端を削る
            title = re.sub(r'\s+', ' ', raw_title).strip() if raw_title else "不明"

            author = "不明"
            publisher = "不明"
            published_date = "不明"
            info_div = report.find("div", class_="column info")
            if info_div:
                p_tag = info_div.find("p")
                if p_tag:
                    info_text = p_tag.get_text(separator=" ", strip=True)
                    parts = [part.strip(' \n\r\t"') for part in info_text.split("--")]
                    if len(parts) > 1:
                        author = re.sub(r'\s+', ' ', parts[1]).strip()
                    if len(parts) > 2:
                        publisher = re.sub(r'\s+', ' ', parts[2]).strip()
                    if len(parts) > 3:
                        published_date = re.sub(r'\s+', ' ', parts[3]).strip()

            if title:
                books.append({
                    "title": title,
                    "author": author,
                    "publisher": publisher,
                    "published_date": published_date,
                    "link": current_url
                })

        # 次ページリンクの取得
        next_li = soup.find("li", class_="next")
        next_link = None
        if next_li:
            next_a = next_li.find("a", href=True)
            if next_a:
                next_link = BASE_URL + next_a["href"]

        if next_link:
            # --- 精密な逆走ガード ---
            # URLから page=数字 を抽出
            match = re.search(r'page=(\d+)', next_link)
            if match:
                next_page_num = int(match.group(1))
                # 例：現ページ(page_count)が6で、次(next_page_num)が1なら停止
                if next_page_num <= page_count:
                    print(f"[DEBUG] ページの逆走または循環を検知（次:{next_page_num}ページ ≦ 現:{page_count}ページ）。抽出を終了します。")
                    break

            # 問題なければ次のページへ更新
            current_url = next_link
            time.sleep(WAIT_TIME)
        else:
            break

    return books


def generate_responsive_html(all_books, output_path):
    """PC/iPhone両対応のレスポンシブHTMLファイルを生成し、要約検索機能を提供する"""
    html_content = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>京都市図書館 新着図書サマリ</title>
    <style>
        body { font-family: sans-serif; padding: 10px; background-color: #f9f9f9; }
        h1 { font-size: 1.2rem; color: #333; }
        .table-container { overflow-x: auto; /* iPhone等での横スクロール対応 */ }
        table { width: 100%; border-collapse: collapse; min-width: 600px; background-color: #fff; }
        th, td { border: 1px solid #ddd; padding: 8px; font-size: 0.9rem; text-align: left; }
        th { background-color: #0056b3; color: #fff; white-space: nowrap; cursor: pointer; user-select: none; }
        th:hover { background-color: #004494; }
        .col-search { width: 90%; box-sizing: border-box; padding: 2px 4px; font-size: 0.85rem; font-weight: normal; }
        .search-row th { background-color: #e9ecef; padding: 4px; cursor: default; }
        .search-row th:hover { background-color: #e9ecef; }
        #clear-filters-btn { background-color: #6c757d; color: white; border: none; border-radius: 4px; padding: 6px 12px; margin-bottom: 10px; cursor: pointer; font-size: 0.9rem; }
        #clear-filters-btn:hover { background-color: #5a6268; }
        .action-btn { background-color: #28a745; color: white; border: none; border-radius: 4px; padding: 6px 12px; margin-bottom: 10px; cursor: pointer; font-size: 0.9rem; margin-right: 5px; }
        .action-btn:hover { background-color: #218838; }
        .toggle-btn-active { background-color: #ffc107 !important; color: #333 !important; }
        .row-kept td { background-color: #fffacd !important; }
        .keep-cb { transform: scale(1.3); cursor: pointer; }
        a { color: #0056b3; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const table = document.getElementById('book-table');
            const tbody = table.querySelector('tbody');
            const rows = Array.from(tbody.querySelectorAll('tr'));

            const sortHeaders = table.querySelectorAll('thead tr:first-child th');
            let currentSortCol = -1;
            let isAsc = true;

            // --- LocalStorageによるキープ状態の管理 ---
            const STORAGE_KEY = 'kyoto_lib_kept_books';
            let keptSet = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));
            const saveKeptBooks = () => { localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(keptSet))); };

            const checkboxes = table.querySelectorAll('.keep-cb');
            checkboxes.forEach(cb => {
                const bookId = cb.dataset.bookId;
                if (keptSet.has(bookId)) {
                    cb.checked = true;
                    cb.closest('tr').classList.add('row-kept');
                }
                cb.addEventListener('change', function() {
                    const tr = this.closest('tr');
                    if (this.checked) {
                        keptSet.add(bookId);
                        tr.classList.add('row-kept');
                    } else {
                        keptSet.delete(bookId);
                        tr.classList.remove('row-kept');
                    }
                    saveKeptBooks();
                    if (isKeptOnlyMode) filterTable();
                });
            });

            sortHeaders.forEach((header, index) => {
                header.dataset.originalText = header.textContent;
                header.addEventListener('click', () => {
                    if (currentSortCol === index) {
                        isAsc = !isAsc;
                    } else {
                        currentSortCol = index;
                        isAsc = true;
                    }
                    sortHeaders.forEach(h => h.textContent = h.dataset.originalText);
                    header.textContent = header.dataset.originalText + (isAsc ? ' ▲' : ' ▼');

                    rows.sort((a, b) => {
                        let valA = a.cells[index].textContent.trim();
                        let valB = b.cells[index].textContent.trim();
                        if (index === 5) { // 出版年月は列追加によりインデックス5に変更
                            const parseDate = (val) => {
                                if (val === '不明') return 0;
                                let parts = val.split('.');
                                return parts.length === 2 ? parseInt(parts[0]) * 100 + parseInt(parts[1]) : (parseInt(val) || 0);
                            };
                            return isAsc ? parseDate(valA) - parseDate(valB) : parseDate(valB) - parseDate(valA);
                        } else {
                            return isAsc ? valA.localeCompare(valB, 'ja') : valB.localeCompare(valA, 'ja');
                        }
                    });
                    rows.forEach(row => tbody.appendChild(row));
                });
            });

            const searchInputs = table.querySelectorAll('.col-search');
            const clearBtn = document.getElementById('clear-filters-btn');
            const normalizeText = (text) => text.normalize('NFKC').toLowerCase();
            let isKeptOnlyMode = false;
            const toggleKeptBtn = document.getElementById('toggle-kept-btn');

            const filterTable = () => {
                const queries = Array.from(searchInputs).map(input => normalizeText(input.value));
                const colMap = [0, 2, 3, 4, 5]; // 検索窓と実際の列(キープ列を除く)のマッピング
                rows.forEach(row => {
                    let isMatch = true;
                    for (let i = 0; i < queries.length; i++) {
                        if (queries[i]) {
                            const cellText = normalizeText(row.cells[colMap[i]].textContent.trim());
                            if (!cellText.includes(queries[i])) {
                                isMatch = false;
                                break;
                            }
                        }
                    }
                    if (isMatch && isKeptOnlyMode) {
                        const cb = row.querySelector('.keep-cb');
                        if (!cb || !cb.checked) isMatch = false;
                    }
                    row.style.display = isMatch ? '' : 'none';
                });
            };
            searchInputs.forEach(input => input.addEventListener('input', filterTable));

            // --- アクションボタンのイベント ---
            document.getElementById('check-all-btn').addEventListener('click', () => {
                rows.forEach(row => {
                    if (row.style.display !== 'none') {
                        const cb = row.querySelector('.keep-cb');
                        if (cb && !cb.checked) { cb.checked = true; cb.dispatchEvent(new Event('change')); }
                    }
                });
            });

            document.getElementById('uncheck-all-btn').addEventListener('click', () => {
                rows.forEach(row => {
                    if (row.style.display !== 'none') {
                        const cb = row.querySelector('.keep-cb');
                        if (cb && cb.checked) { cb.checked = false; cb.dispatchEvent(new Event('change')); }
                    }
                });
            });

            toggleKeptBtn.addEventListener('click', () => {
                isKeptOnlyMode = !isKeptOnlyMode;
                toggleKeptBtn.textContent = isKeptOnlyMode ? 'チェックのみ表示(解除)' : 'チェックのみ表示';
                if (isKeptOnlyMode) toggleKeptBtn.classList.add('toggle-btn-active');
                else toggleKeptBtn.classList.remove('toggle-btn-active');
                filterTable();
            });

            clearBtn.addEventListener('click', () => {
                searchInputs.forEach(input => input.value = '');
                if (isKeptOnlyMode) {
                    isKeptOnlyMode = false;
                    toggleKeptBtn.textContent = 'チェックのみ表示';
                    toggleKeptBtn.classList.remove('toggle-btn-active');
                }
                filterTable();
            });
        });
    </script>
</head>
<body>
    <h1>京都市図書館 新着図書サマリ</h1>
    <div style="margin-bottom: 10px;">
        <button id="clear-filters-btn">全フィルタ解除</button>
        <button id="check-all-btn" class="action-btn">全チェック</button>
        <button id="uncheck-all-btn" class="action-btn">全チェック解除</button>
        <button id="toggle-kept-btn" class="action-btn" style="background-color: #17a2b8;">チェックのみ表示</button>
    </div>
    <div class="table-container">
        <table id="book-table">
            <thead>
                <tr>
                    <th>分類</th>
                    <th>キープ</th>
                    <th>書籍名</th>
                    <th>作者</th>
                    <th>出版社</th>
                    <th>出版年月</th>
                    <th>検索</th>
                </tr>
                <tr class="search-row">
                    <th><input type="text" class="col-search" placeholder="分類を検索..."></th>
                    <th></th>
                    <th><input type="text" class="col-search" placeholder="書籍名を検索..."></th>
                    <th><input type="text" class="col-search" placeholder="作者を検索..."></th>
                    <th><input type="text" class="col-search" placeholder="出版社を検索..."></th>
                    <th><input type="text" class="col-search" placeholder="年月を検索..."></th>
                    <th></th>
                </tr>
            </thead>
            <tbody>
"""
    for item in all_books:
        # 書籍名エスケープ
        safe_title = item['title'].replace('"', '&quot;')
        safe_book_id = f"{item['title']}_{item['author']}".replace('"', '&quot;')

        # 作者名のクレンジング（「／」があればそれより前のみを検索ワードにする）
        clean_author = item['author'].split('／')[0] if item['author'] != "不明" else "不明"
        safe_author = clean_author.replace('"', '&quot;')

        # 出版社名エスケープ
        safe_publisher = item['publisher'].replace('"', '&quot;') if item['publisher'] != "不明" else "不明"

        # 作者セルと出版社セルのフォーム生成ロジック（不明時はリンクなし）
        author_cell_content = f"""<form method="POST" action="https://www.kyotocitylib.jp/winj/opac/search-standard.do?lang=ja" target="_blank" style="display:inline; margin:0; padding:0;">
                            <input type="hidden" name="txt_word" value="{safe_author}">
                            <input type="hidden" name="hid_word_column" value="fulltext">
                            <input type="hidden" name="submit_btn_searchEasy" value="検索">
                            <a href="#" onclick="this.closest('form').submit(); return false;">{item['author']}</a>
                        </form>""" if item['author'] != "不明" else item['author']

        publisher_cell_content = f"""<form method="POST" action="https://www.kyotocitylib.jp/winj/opac/search-standard.do?lang=ja" target="_blank" style="display:inline; margin:0; padding:0;">
                            <input type="hidden" name="txt_word" value="{safe_publisher}">
                            <input type="hidden" name="hid_word_column" value="fulltext">
                            <input type="hidden" name="submit_btn_searchEasy" value="検索">
                            <a href="#" onclick="this.closest('form').submit(); return false;">{item['publisher']}</a>
                        </form>""" if item['publisher'] != "不明" else item['publisher']

        # --- 良質な要約・書評サイトのみを狙い撃つ串刺し検索クエリの構築 ---
        search_query = f'"{item["title"]}"'
        if clean_author != "不明":
            search_query += f' "{clean_author}"'

        search_query += ' (site:flierinc.com OR site:note.com OR site:youtube.com OR site:qiita.com OR site:zenn.dev OR site:hatenablog.com OR site:bookbang.jp OR site:bookmeter.com) 要約 OR 感想 OR 書評'

        # 日本語やスペースをURL用エンコードに変換
        encoded_query = urllib.parse.quote(search_query)
        review_search_url = f"https://www.google.com/search?q={encoded_query}"

        html_content += f"""                <tr>
                    <td>{item['category']}</td>
                    <td style="text-align: center;"><input type="checkbox" class="keep-cb" data-book-id="{safe_book_id}"></td>
                    <td>
                        <form method="POST" action="https://www.kyotocitylib.jp/winj/opac/search-standard.do?lang=ja" target="_blank" style="display:inline; margin:0; padding:0;">
                            <input type="hidden" name="txt_word" value="{safe_title}">
                            <input type="hidden" name="hid_word_column" value="fulltext">
                            <input type="hidden" name="submit_btn_searchEasy" value="検索">
                            <a href="#" onclick="this.closest('form').submit(); return false;">{item['title']}</a>
                        </form>
                    </td>
                    <td>{author_cell_content}</td>
                    <td>{publisher_cell_content}</td>
                    <td>{item['published_date']}</td>
                    <td style="text-align: center; white-space: nowrap;"><a href="{review_search_url}" target="_blank" style="text-decoration:none; font-weight:bold; color:#0056b3;" title="良質な要約・実践レビューを検索">🔍 検索</a></td>
                </tr>
"""

    html_content += """            </tbody>
        </table>
    </div>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[INFO] HTMLファイルを生成しました: {output_path}")


def main():
    setup_directory()

    with requests.Session() as session:
        # 履歴データのロード (HISTORY_FILE はスクリプト同フォルダ)
        history = {}
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception as e:
                print(f"[WARN] 履歴ファイルの読み込みに失敗しました: {e}")

        try:
            categories = fetch_category_links(session)
        except Exception as e:
            print(f"[ERROR] トップページの取得に失敗しました: {e}")
            return

        today_str = datetime.date.today().isoformat()

        # 履歴データの新構造への強制マイグレーション
        for cat in categories:
            cat_name = cat["name"]
            current_site_count = cat["count_num"]
            old_data = history.get(cat_name, {})

            if isinstance(old_data, int):
                history[cat_name] = {"prev_count": old_data, "latest_count": old_data, "last_update_date": "1970-01-01", "known_books": [], "new_books_count": 0}
            elif "count" in old_data:
                c = old_data["count"]
                history[cat_name] = {"prev_count": c, "latest_count": c, "last_update_date": "1970-01-01", "known_books": old_data.get("known_books", []), "new_books_count": 0}
            elif "prev_count" not in old_data:
                history[cat_name] = {"prev_count": current_site_count, "latest_count": current_site_count, "last_update_date": "1970-01-01", "known_books": [], "new_books_count": 0}
            else:
                if "new_books_count" not in history[cat_name]:
                    history[cat_name]["new_books_count"] = 0

        # --- 自動実行（サイレント）モードの判定 ---
        import sys
        is_auto_mode = "--auto" in sys.argv

        while True:
            all_books = []

            if is_auto_mode:
                print("[INFO] 自動実行モード（--auto）で開始します。全分類の新着のみをバックグラウンドで抽出します。")
                filtered_categories = categories
                filter_start = None
                filter_end = None
                is_only_new = True
            else:
                # UIから対象カテゴリと年月条件、新着フラグを受け取る
                ui_result = select_categories_ui(categories, history)

                if ui_result[0] is None:
                    print("[INFO] UIが閉じられたため、プログラムを終了します。")
                    break

                filtered_categories, filter_start, filter_end, is_only_new = ui_result

                if not filtered_categories:
                    print("[WARN] 抽出対象が選択されませんでした。")
                    continue

            for cat in filtered_categories:
                try:
                    books = fetch_books_from_category(session, cat["url"])

                    # 今回サイト上に存在したすべての本（フィルタ適用前）のリストを作成
                    current_known_books = [f"{b['title']}_{b['author']}" for b in books]
                    # 過去の既知本リストを取得
                    past_known_books = history.get(cat["name"], {}).get("known_books", [])

                    newly_found_count = 0

                    for b in books:
                        book_key = f"{b['title']}_{b['author']}"

                        # 純粋な新着をカウント
                        if book_key not in past_known_books:
                            newly_found_count += 1

                        # --- 新着フィルタリング ---
                        if is_only_new and (book_key in past_known_books):
                            continue # 過去に取得済みの本は除外

                        # --- 出版年月のフィルタリング ---
                        if filter_start is not None or filter_end is not None:
                            pub_date = b["published_date"]
                            if pub_date == "不明":
                                continue # 指定ありの場合は不明を捨てる

                            # 例: 2026.1 -> 202601 のように整数化して比較
                            match = re.search(r'(\d{4})\.(\d{1,2})', pub_date)
                            if match:
                                b_val = int(match.group(1)) * 100 + int(match.group(2))
                                if filter_start is not None and b_val < filter_start:
                                    continue
                                if filter_end is not None and b_val > filter_end:
                                    continue
                            else:
                                continue # yyyy.m 形式から外れる異常データも捨てる

                        b["category"] = cat["name"]
                        all_books.append(b)

                    # 抽出がエラーなく完了した場合のみ、日付ベースの履歴更新とパージを実施
                    h_data = history[cat["name"]]
                    last_date = h_data.get("last_update_date", "1970-01-01")

                    if last_date < today_str:
                        h_data["prev_count"] = h_data.get("latest_count", 0)
                        h_data["new_books_count"] = newly_found_count # 日付が変わったので新規カウント
                    else:
                        h_data["new_books_count"] = h_data.get("new_books_count", 0) + newly_found_count # 同日なら累計加算

                    h_data["latest_count"] = cat["count_num"]
                    h_data["last_update_date"] = today_str
                    h_data["known_books"] = current_known_books

                    try:
                        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                            json.dump(history, f, ensure_ascii=False, indent=4)
                    except Exception as e:
                        print(f"[WARN] 履歴の保存に失敗しました: {e}")

                except Exception as e:
                    print(f"[WARN] 分類 '{cat['name']}' の取得中にエラーが発生しスキップしました: {e}")
                    continue

            # 0件でも空のHTMLを表示する仕様
            now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"Library_new_stock_summary_{now_str}.html"
            output_path = os.path.join(OUTPUT_DIR, output_filename)
            generate_responsive_html(all_books, output_path)

            if not all_books:
                print(f"[INFO] 新着または条件に合致する本はありませんでした。サマリーシートを生成しました: {output_filename}")
            else:
                print(f"[INFO] サマリーシートを生成しました: {output_filename}")

            if not is_auto_mode:
                webbrowser.open('file://' + os.path.realpath(output_path))
            else:
                print("[INFO] 自動実行モードのため処理を完了し、スクリプトを終了します。")
                break


if __name__ == "__main__":
    print("[INFO] 処理を開始します...")
    main()
    print("[INFO] 全ての処理が完了しました。")
