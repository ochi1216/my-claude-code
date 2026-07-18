# -*- coding: utf-8 -*-
"""共通スキーマ・configローダー・fact構造ヘルパー。

DESIGN_analog_ic_se_strategy_organizer.md 3章(fact構造)・5章(カテゴリスキーマ)・
6章(競合企業DB)の実装。config/*.json はデータ、本モジュールはそれを読む薄いローダー。
"""

import os
import json
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
CATEGORY_SCHEMA_PATH = os.path.join(CONFIG_DIR, "category_schema.json")
COMPETITORS_DB_PATH = os.path.join(CONFIG_DIR, "competitors_db.json")
OWN_COMPANY_PATH = os.path.join(CONFIG_DIR, "own_company.json")

# --- fact構造（DESIGN 3章） -------------------------------------------------

SOURCE_TYPES = ("TI_official", "third_party", "llm_estimate", "user_input")
CONFIDENCE_LEVELS = ("high", "medium", "low")

# Excelに存在する9カテゴリ以外をLLMが返した場合のフォールバック。
# category_schema.json はExcel実データに準拠させる方針のため、汎用カテゴリは
# config化せずここにコード側の既定値として持つ（DESIGN 11章 要検証事項4）。
GENERIC_CATEGORY_KEY = "generic_analog_ic"
GENERIC_CATEGORY = {
    "label": "その他アナログ/電源IC（カテゴリ未確定時のフォールバック）",
    "excel_column": None,
    "parameters": [
        {"key": "input_voltage_range", "label": "入力電圧範囲", "unit": "V", "type": "range"},
        {"key": "quiescent_current", "label": "静止/動作電流", "unit": "µA", "type": "number"},
        {"key": "package", "label": "パッケージ", "unit": "", "type": "string"},
        {"key": "temp_grade", "label": "動作温度グレード", "unit": "℃", "type": "string"},
        {"key": "price_1ku_usd", "label": "参考単価(1000個時)", "unit": "USD", "type": "number"},
    ],
}


def make_fact(value, source_type, confidence, unit=None, source_detail="", source_url="",
              as_of=None, note=""):
    """fact構造(DESIGN 3章)を組み立てる。source_type/confidenceが不正な場合はconfidence="low"に倒す。"""
    if source_type not in SOURCE_TYPES:
        note = (note + f" [不正なsource_type: {source_type}]").strip()
        source_type = "llm_estimate"
        confidence = "low"
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "low"
    return {
        "value": value,
        "unit": unit or "",
        "source_type": source_type,
        "source_detail": source_detail,
        "source_url": source_url,
        "confidence": confidence,
        "as_of": as_of or date.today().isoformat(),
        "note": note,
    }


def normalize_fact(obj):
    """LLM出力（dict想定）を安全なfact構造に正規化する。

    必須キー欠落・型不正の場合はconfidence="low"に倒して欠落を埋める（DESIGN 3章の方針）。
    dict以外（生の値がそのまま返ってきた場合等）はllm_estimate/lowのfactでラップする。
    """
    if not isinstance(obj, dict) or "value" not in obj:
        return make_fact(obj, "llm_estimate", "low", note="fact構造でない値を正規化")
    source_type = obj.get("source_type")
    confidence = obj.get("confidence")
    return make_fact(
        obj.get("value"), source_type, confidence,
        unit=obj.get("unit", ""), source_detail=obj.get("source_detail", ""),
        source_url=obj.get("source_url", ""), as_of=obj.get("as_of"), note=obj.get("note", ""),
    )


# --- config/category_schema.json ローダー -----------------------------------

_category_schema_cache = None


def load_category_schema(config_dir=None, force=False):
    """config/category_schema.jsonを読み込む（プロセス内キャッシュ）。"""
    global _category_schema_cache
    if _category_schema_cache is not None and not force and config_dir is None:
        return _category_schema_cache
    path = os.path.join(config_dir, "category_schema.json") if config_dir else CATEGORY_SCHEMA_PATH
    with open(path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    if config_dir is None:
        _category_schema_cache = schema
    return schema


def resolve_category(category_key, config_dir=None):
    """カテゴリキーからカテゴリ定義dict({label, parameters,...})を返す。

    9カテゴリのいずれにも一致しない場合はGENERIC_CATEGORYにフォールバックする。
    """
    schema = load_category_schema(config_dir=config_dir)
    categories = schema.get("categories", {})
    if category_key in categories:
        return category_key, categories[category_key]
    return GENERIC_CATEGORY_KEY, GENERIC_CATEGORY


def category_keys(config_dir=None):
    """比較可能な全カテゴリキー（9カテゴリ＋フォールバック）を返す。"""
    schema = load_category_schema(config_dir=config_dir)
    return list(schema.get("categories", {}).keys()) + [GENERIC_CATEGORY_KEY]


# --- config/competitors_db.json ローダー -------------------------------------

_competitors_db_cache = None


def load_competitors_db(config_dir=None, force=False):
    """config/competitors_db.json全体を読み込む（プロセス内キャッシュ）。"""
    global _competitors_db_cache
    if _competitors_db_cache is not None and not force and config_dir is None:
        return _competitors_db_cache
    path = os.path.join(config_dir, "competitors_db.json") if config_dir else COMPETITORS_DB_PATH
    with open(path, "r", encoding="utf-8") as f:
        db = json.load(f)
    if config_dir is None:
        _competitors_db_cache = db
    return db


def load_competitors(category_key=None, active_only=True, min_level="limited", config_dir=None):
    """競合企業一覧を返す。

    category_key指定時は、そのカテゴリで min_level 以上（primary優先、limitedも含む）の
    企業のみに絞り込む。region昇順→breadth_score降順でソートする
    （DESIGN 8.4節: 地域バランスを考慮した選定の下準備）。
    """
    db = load_competitors_db(config_dir=config_dir)
    companies = db.get("companies", [])
    if active_only:
        companies = [c for c in companies if c.get("active", True)]
    if category_key:
        levels = {"primary": 2, "limited": 1, "none": 0}
        threshold = levels.get(min_level, 1)
        companies = [
            c for c in companies
            if levels.get(c.get("categories", {}).get(category_key, "none"), 0) >= threshold
        ]
    return sorted(companies, key=lambda c: (c.get("region", ""), -(c.get("breadth_score") or 0)))


def competitors_summary(config_dir=None):
    """競合企業DBの俯瞰用サマリー（地域別社数・カテゴリ別primary/limited社数・breadth_score分布）"""
    db = load_competitors_db(config_dir=config_dir)
    companies = [c for c in db.get("companies", []) if c.get("active", True)]
    region_counts = {}
    category_counts = {key: {"primary": 0, "limited": 0} for key in db.get("categories", [])}
    scores = []
    for c in companies:
        region_counts[c.get("region", "")] = region_counts.get(c.get("region", ""), 0) + 1
        if isinstance(c.get("breadth_score"), (int, float)):
            scores.append(c["breadth_score"])
        for cat_key, level in (c.get("categories", {}) or {}).items():
            if cat_key in category_counts and level in ("primary", "limited"):
                category_counts[cat_key][level] += 1
    return {
        "total_companies": len(companies),
        "as_of": db.get("as_of", ""),
        "region_counts": region_counts,
        "category_counts": category_counts,
        "breadth_score_avg": round(sum(scores) / len(scores), 2) if scores else None,
    }


def pick_regional_representatives(category_key=None, config_dir=None):
    """地域ごとにbreadth_score最上位1社を選ぶ（DESIGN 8.4節「通常モード」用）。"""
    companies = load_competitors(category_key=category_key, config_dir=config_dir)
    best_by_region = {}
    for c in companies:
        region = c.get("region", "")
        if region not in best_by_region or (c.get("breadth_score") or 0) > (best_by_region[region].get("breadth_score") or 0):
            best_by_region[region] = c
    return list(best_by_region.values())


# --- config/own_company.json ローダー（自社＝Nexperia、ベンチマーク対象＝TI） ------

def load_own_company(config_dir=None):
    """config/own_company.jsonを読み込む。無ければNoneを返す（自社設定は必須にしない）。"""
    path = os.path.join(config_dir, "own_company.json") if config_dir else OWN_COMPANY_PATH
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def own_company_name(config_dir=None):
    """自社名（例: "Nexperia"）を返す。未設定ならNone。"""
    oc = load_own_company(config_dir=config_dir)
    return oc.get("name") if oc else None


def find_company(name, config_dir=None):
    """competitors_db.jsonから企業名（大文字小文字区別なし）で1社を検索する。"""
    if not name:
        return None
    db = load_competitors_db(config_dir=config_dir)
    target = name.strip().lower()
    for c in db.get("companies", []):
        if c.get("name", "").strip().lower() == target:
            return c
    return None


# --- ホワイトスペース分析（competitors_db.jsonのみで算出、LLM呼び出し不要） --------

def whitespace_analysis(config_dir=None):
    """カテゴリ別の「手薄度（ホワイトスペーススコア）」を競合DBの集計だけで算出する。

    観点は3つ:
    1. カテゴリ全体のホワイトスペース度: primary/limited企業が少ないカテゴリほど
       まだ本気で作っている会社が少ない＝参入余地が大きいと見なす
       （whitespace_score = 1 - coverage_score, coverage_score = (primary数 + limited数*0.5) / 総社数）
    2. 車載クロスのホワイトスペース度: そのカテゴリのprimary/limited企業のうち、
       車載対応(automotive_capable=primary)企業が占める割合が低いほど、
       「車載版」だけがまだ手薄（Excelのメソドロジーが例示した「車載LED診断」等のパターン）
    3. 地域別の手薄さ: 地域ごとのprimary企業密度を比較し、最も手薄な地域を特定する

    加えて、config/own_company.json で設定された自社（Nexperia）がそのカテゴリで
    どのレベル（primary/limited/none）にいるかを併記し、
    「自社がまだ弱い×市場全体も手薄」＝最優先の企画候補、を判別しやすくする。

    戻り値: whitespace_score降順のリスト。返り値をLLMに渡す必要はなく、
    ダッシュボードのポートフォリオ俯瞰タブでそのままテーブル/グラフ化する想定。
    """
    db = load_competitors_db(config_dir=config_dir)
    companies = [c for c in db.get("companies", []) if c.get("active", True)]
    categories = db.get("categories", [])
    category_labels = load_category_schema(config_dir=config_dir).get("categories", {})

    total = len(companies)
    regions = sorted({c.get("region", "") for c in companies if c.get("region")})

    own_name = own_company_name(config_dir=config_dir)
    own_company = find_company(own_name, config_dir=config_dir) if own_name else None

    results = []
    for cat in categories:
        primary = [c for c in companies if c.get("categories", {}).get(cat) == "primary"]
        limited = [c for c in companies if c.get("categories", {}).get(cat) == "limited"]
        primary_count = len(primary)
        limited_count = len(limited)
        none_count = total - primary_count - limited_count
        coverage_score = (primary_count + limited_count * 0.5) / total if total else 0.0
        whitespace_score = round(1 - coverage_score, 3)

        active_players = primary + limited
        if active_players:
            auto_primary_count = sum(1 for c in active_players if c.get("automotive_capable") == "primary")
            automotive_overlap_ratio = round(auto_primary_count / len(active_players), 3)
            automotive_whitespace_score = round(1 - automotive_overlap_ratio, 3)
        else:
            automotive_overlap_ratio = None
            automotive_whitespace_score = None

        region_primary_share = {}
        for region in regions:
            region_companies = [c for c in companies if c.get("region") == region]
            region_primary = sum(1 for c in region_companies if c.get("categories", {}).get(cat) == "primary")
            region_primary_share[region] = round(region_primary / len(region_companies), 3) if region_companies else 0.0
        weakest_region = min(region_primary_share, key=region_primary_share.get) if region_primary_share else None

        results.append({
            "category": cat,
            "label": category_labels.get(cat, {}).get("label", cat),
            "primary_count": primary_count,
            "limited_count": limited_count,
            "none_count": none_count,
            "coverage_score": round(coverage_score, 3),
            "whitespace_score": whitespace_score,
            "automotive_overlap_ratio": automotive_overlap_ratio,
            "automotive_whitespace_score": automotive_whitespace_score,
            "region_primary_share": region_primary_share,
            "weakest_region": weakest_region,
            "own_company_name": own_name,
            "own_company_status": (own_company.get("categories", {}).get(cat, "none")
                                    if own_company else None),
        })

    results.sort(key=lambda r: r["whitespace_score"], reverse=True)
    return results
