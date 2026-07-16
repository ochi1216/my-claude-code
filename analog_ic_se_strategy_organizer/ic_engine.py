# -*- coding: utf-8 -*-
"""一気通貫 TI製品競合分析パイプライン。

型番1つを入力に、5ステージ（製品取り込み→市場分析→キーカスタマー推定→
競合IC比較→次世代スペック提案）を順に実行し、結果dict
（metadata/classifiers/content の3層構造、ic_index.save_product_case()で
そのままproduct_lakeに保存できる形）を返す。Streamlitには依存しない。

rtocs_organizer/strategy_engine.py のアーキテクチャをそのまま移植している:
- 各ステージは失敗しても {"error": ...} を格納して続行する（部分レポート方針）
- コストはトークン→USD→円換算で集計
- ステージ0〜3はGoogle Search Grounding（google-genai SDK, google_searchツール）を使用。
  レガシーの google-generativeai は google_search_retrieval しか公開しておらず
  Gemini 2.x系では400エラーになるため、grounding専用に google-genai を使う
  （rtocs_organizer開発時に実機で確認済みの教訓）
"""

import os
import json
from datetime import datetime

import ic_schema
import ic_prompts as P

# 100万トークンあたりの単価（USD）: (入力, 出力)。rtocs_organizerと同じ単価表。
MODEL_PRICING = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
}
USD_JPY = 160

STAGE_LABELS = [
    ("stage0_product", "① 製品取り込み"),
    ("stage1_market", "② 市場分析"),
    ("stage2_key_customers", "③ キーカスタマー推定"),
    ("stage3_competitors", "④ 競合IC比較"),
    ("stage4_next_gen", "⑤ 次世代スペック提案"),
]


def _strip_code_fence(text):
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


class GeminiClient:
    """JSONモード呼び出し＋Google Search Grounding＋コスト集計のラッパー"""

    def __init__(self, api_key=None, model_name="gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self.total_cost_usd = 0.0
        self.stage_costs_jpy = {}
        self._model = None
        self._genai2_client = None
        if self.api_key:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(model_name)

    @property
    def total_cost_jpy(self):
        return self.total_cost_usd * USD_JPY

    def _add_cost(self, stage, response):
        usage = getattr(response, "usage_metadata", None)
        t_in = getattr(usage, "prompt_token_count", 0) or 0
        t_out = getattr(usage, "candidates_token_count", 0) or 0
        p_in, p_out = MODEL_PRICING.get(self.model_name, MODEL_PRICING["gemini-2.5-flash"])
        cost = (t_in / 1_000_000 * p_in) + (t_out / 1_000_000 * p_out)
        self.total_cost_usd += cost
        self.stage_costs_jpy[stage] = self.stage_costs_jpy.get(stage, 0.0) + cost * USD_JPY

    def generate_json(self, prompt, stage="misc", retries=1):
        """JSONモードで呼び出しdictを返す。失敗時はValueError"""
        if not self._model:
            raise ValueError("GEMINI_API_KEY が設定されていません。")
        last_err = None
        for _ in range(retries + 1):
            try:
                response = self._model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"},
                )
                self._add_cost(stage, response)
                if not response.text:
                    raise ValueError("空の応答")
                return json.loads(_strip_code_fence(response.text))
            except Exception as e:
                last_err = e
        raise ValueError(f"Gemini呼び出し失敗: {last_err}")

    def _get_genai2_client(self):
        """Google Search Grounding用の新SDK(google-genai)クライアントを遅延生成する。

        レガシーの`google-generativeai`が公開するTool型は`google_search_retrieval`
        （Gemini 1.5世代向けの旧グラウンディング方式）のみで、Gemini 2.x系が要求する
        `google_search`ツールとはAPI形状が異なり使えない。後継の統合SDK`google-genai`
        （別パッケージ、共存可能）のみがgoogle_searchツールを公開しているため、
        検索グラウンディングを使う全ステージでこちらを使う。
        """
        if self._genai2_client is None:
            from google import genai as genai2
            self._genai2_client = genai2.Client(api_key=self.api_key)
        return self._genai2_client

    def generate_grounded_json(self, prompt, stage="misc", retries=1):
        """Google Search Groundingを有効にした呼び出し（google-genai SDK使用）。

        グラウンディングとJSONモード(response_mime_type)は併用できないため、
        プロンプト側にJSON形式での出力を指示し、コードフェンス除去＋json.loadsでパースする。
        """
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY が設定されていません。")
        from google.genai import types as genai2_types
        last_err = None
        for _ in range(retries + 1):
            try:
                client = self._get_genai2_client()
                config = genai2_types.GenerateContentConfig(
                    tools=[genai2_types.Tool(google_search=genai2_types.GoogleSearch())]
                )
                response = client.models.generate_content(
                    model=self.model_name, contents=prompt, config=config)
                self._add_cost(stage, response)
                if not response.text:
                    raise ValueError("空の応答")
                return json.loads(_strip_code_fence(response.text))
            except Exception as e:
                last_err = e
        raise ValueError(f"Gemini(grounding)呼び出し失敗: {last_err}")


def _fact_value(fact, default=""):
    """fact構造（またはそれ以外の生値）からvalueだけを取り出す"""
    if isinstance(fact, dict) and "value" in fact:
        return fact.get("value", default)
    return fact if fact is not None else default


def _categories_overview_text(schema):
    """ステージ0用: 全カテゴリのキー・ラベル・パラメータ一覧を1カテゴリ1行のテキストに整形"""
    lines = []
    for key, cat in schema.get("categories", {}).items():
        params = ", ".join(
            f"{p['key']}({p.get('unit','')})" if p.get("unit") else p["key"]
            for p in cat.get("parameters", [])
        )
        lines.append(f"- {key} ({cat.get('label','')}): {params}")
    return "\n".join(lines)


def _category_params_text(category_def):
    """ステージ0で選ばれたカテゴリ／ステージ3用: 1カテゴリ分のパラメータ一覧テキスト"""
    lines = []
    for p in category_def.get("parameters", []):
        unit = f" [{p['unit']}]" if p.get("unit") else ""
        note = f" ({p['note']})" if p.get("note") else ""
        lines.append(f"- {p['key']}{unit}: {p.get('label','')}{note}")
    return "\n".join(lines)


class IcPipeline:
    def __init__(self, api_key=None, deep=False, data_dir=None, progress_cb=None,
                 competitor_mode="normal"):
        self.deep = deep
        self.model_name = "gemini-2.5-pro" if deep else "gemini-2.5-flash"
        self.client = GeminiClient(api_key=api_key, model_name=self.model_name)
        self.data_dir = data_dir or ic_schema.BASE_DIR
        self.progress_cb = progress_cb or (lambda key, label, status: None)
        self.competitor_mode = competitor_mode  # "normal"(地域代表1社ずつ) or "full"(該当カテゴリ全社)

    def _run_stage(self, key, label, fn, stages):
        self.progress_cb(key, label, "start")
        try:
            stages[key] = fn()
            self.progress_cb(key, label, "done")
        except Exception as e:
            stages[key] = {"error": f"取得失敗: {e}"}
            self.progress_cb(key, label, "error")

    def run_pipeline(self, part_number, category_hint=None, only_stage0=False):
        """5ステージを実行する。only_stage0=Trueなら製品取り込みのみ実行し、
        1〜4は明示的にスキップする（ダッシュボードの「ステージ0のみ実行」ボタン用、
        軽量登録・低コストでの型番・カテゴリ確認に使う）。
        """
        stages = {}
        labels = dict(STAGE_LABELS)
        schema = ic_schema.load_category_schema()

        # ① 製品取り込み（Google Search Grounding）
        def stage0():
            hint_note = (
                f'越智さんが事前にカテゴリ「{category_hint}」を指定しています。'
                f'公式カタログの分類と矛盾がなければそれを採用してください。' if category_hint else ""
            )
            prompt = P.STAGE0_PRODUCT.format(
                part_number=part_number,
                category_hint_note=hint_note,
                category_list=", ".join(schema.get("categories", {}).keys()),
                category_params_overview=_categories_overview_text(schema),
            )
            return self.client.generate_grounded_json(prompt, stage="stage0_product")
        self._run_stage("stage0_product", labels["stage0_product"], stage0, stages)
        s0 = stages.get("stage0_product", {})

        raw_category = _fact_value(s0.get("category")) if "error" not in s0 else ""
        category_key, category_def = ic_schema.resolve_category(str(raw_category or ""))
        apps = []
        if "error" not in s0:
            apps = [_fact_value(a) for a in (s0.get("applications") or []) if _fact_value(a)]

        # ② 市場分析（Google Search Grounding）
        def stage1():
            if only_stage0:
                return {"skipped": "「ステージ0のみ実行」モードのためスキップ"}
            if "error" in s0:
                return {"skipped": "製品取り込みが失敗したためスキップ"}
            if not apps:
                return {"skipped": "アプリケーション情報が得られなかったためスキップ"}
            prompt = P.STAGE1_MARKET.format(
                part_number=part_number, category=category_key,
                applications_json=json.dumps(apps, ensure_ascii=False))
            return self.client.generate_grounded_json(prompt, stage="stage1_market")
        self._run_stage("stage1_market", labels["stage1_market"], stage1, stages)

        # ③ キーカスタマー推定（Google Search Grounding、公開情報のみ）
        def stage2():
            if only_stage0:
                return {"skipped": "「ステージ0のみ実行」モードのためスキップ"}
            if "error" in s0:
                return {"skipped": "製品取り込みが失敗したためスキップ"}
            if not apps:
                return {"skipped": "アプリケーション情報が得られなかったためスキップ"}
            prompt = P.STAGE2_KEY_CUSTOMERS.format(
                part_number=part_number, category=category_key,
                applications_json=json.dumps(apps, ensure_ascii=False))
            return self.client.generate_grounded_json(prompt, stage="stage2_key_customers")
        self._run_stage("stage2_key_customers", labels["stage2_key_customers"], stage2, stages)

        # ④ 競合IC比較（competitors_db.jsonから対象企業を抽出し1社ずつ検索）
        def stage3():
            if only_stage0:
                return {"skipped": "「ステージ0のみ実行」モードのためスキップ"}
            if "error" in s0:
                return {"skipped": "製品取り込みが失敗したためスキップ"}
            if self.competitor_mode == "full":
                companies = ic_schema.load_competitors(category_key=category_key)
            else:
                companies = ic_schema.pick_regional_representatives(category_key=category_key)
            if not companies:
                return {"skipped": f"カテゴリ'{category_key}'に該当する競合企業がcompetitors_db.jsonに見つかりませんでした"}

            key_specs = s0.get("key_specs", {}) if isinstance(s0.get("key_specs"), dict) else {}
            specs_summary = ", ".join(
                f"{k}={_fact_value(v)}" for k, v in list(key_specs.items())[:6]
            ) or "(仕様値未取得)"
            params_overview = _category_params_text(category_def)

            results = []
            for c in companies:
                try:
                    prompt = P.STAGE3_COMPETITOR.format(
                        company=c.get("name", ""), region=c.get("region", ""),
                        company_type=c.get("company_type", ""), part_number=part_number,
                        category=category_key, ti_key_specs_summary=specs_summary,
                        category_params_overview=params_overview)
                    out = self.client.generate_grounded_json(prompt, stage="stage3_competitors")
                    out["lookup_status"] = "ok"
                    results.append(out)
                except Exception as e:
                    results.append({"company": c.get("name", ""), "region": c.get("region", ""),
                                     "lookup_status": "error", "error": f"検索失敗: {e}"})
            if all(r.get("lookup_status") == "error" for r in results):
                return {"error": "全競合企業の検索に失敗しました"}
            return {"competitors": results, "comparison_table_note": ""}
        self._run_stage("stage3_competitors", labels["stage3_competitors"], stage3, stages)

        # ⑤ 次世代スペック提案（JSONモード、grounding不要）
        def stage4():
            if only_stage0:
                return {"skipped": "「ステージ0のみ実行」モードのためスキップ"}
            if "error" in s0:
                return {"skipped": "製品取り込みが失敗したためスキップ"}

            def _safe(key):
                s = stages.get(key, {})
                return json.dumps(s, ensure_ascii=False) if isinstance(s, dict) and "error" not in s else "{}"

            prompt = P.STAGE4_NEXT_GEN.format(
                part_number=part_number, category=category_key,
                stage0_json=_safe("stage0_product"), stage1_json=_safe("stage1_market"),
                stage2_json=_safe("stage2_key_customers"), stage3_json=_safe("stage3_competitors"))
            return self.client.generate_json(prompt, stage="stage4_next_gen")
        self._run_stage("stage4_next_gen", labels["stage4_next_gen"], stage4, stages)

        # --- 結果の組み立て（product_lake保存形式: metadata/classifiers/content） ---
        stage_status = {}
        for key, _ in STAGE_LABELS:
            s = stages.get(key, {})
            if "error" in s:
                stage_status[key] = "error"
            elif "skipped" in s:
                stage_status[key] = "skipped"
            else:
                stage_status[key] = "done"

        top_priority_kpi = ""
        s4 = stages.get("stage4_next_gen", {})
        if isinstance(s4, dict) and s4.get("proposed_specs"):
            top = s4["proposed_specs"][0]
            top_priority_kpi = top.get("kpi", "")

        s3 = stages.get("stage3_competitors", {})
        regions_covered = sorted({
            r.get("region", "") for r in (s3.get("competitors", []) if isinstance(s3, dict) else [])
            if r.get("region")
        })

        return {
            "metadata": {
                "part_number": part_number,
                "manufacturer": "Texas Instruments",
                "analyzed_at": datetime.now().isoformat(),
                "pipeline_mode": "deep" if self.deep else "flash",
                "model": self.model_name,
                "schema_version": 1,
                "stage_status": stage_status,
            },
            "classifiers": {
                "category": category_key,
                "category_confirmed_by_user": bool(category_hint),
                "applications_short": apps[:5],
                "regions_covered": regions_covered,
                "top_priority_kpi": top_priority_kpi,
            },
            "content": {
                "stage0_product": s0,
                "stage1_market": stages.get("stage1_market", {}),
                "stage2_key_customers": stages.get("stage2_key_customers", {}),
                "stage3_competitors": s3,
                "stage4_next_gen_proposal": s4,
            },
            "costs": {
                "stages_jpy": {k: round(v, 2) for k, v in self.client.stage_costs_jpy.items()},
                "total_usd": round(self.client.total_cost_usd, 4),
                "total_jpy": round(self.client.total_cost_jpy, 2),
            },
        }


def generate_portfolio_commentary(records, competitor_summary, api_key=None, model_name="gemini-2.5-flash"):
    """ポートフォリオ俯瞰タブ用: ケースライブラリ全件の俯瞰総評を生成する（rtocs_organizerの
    generate_trend_commentary と同型）。

    戻り値: (markdown文字列, コスト円)
    """
    import ic_index

    client = GeminiClient(api_key=api_key, model_name=model_name)
    prompt = P.PORTFOLIO_COMMENTARY.format(
        case_index=ic_index.compact_index_for_llm(records) or "(分析済み製品がありません)",
        competitor_summary=json.dumps(competitor_summary, ensure_ascii=False))
    out = client.generate_json(prompt, stage="portfolio_commentary")
    return out.get("commentary_markdown", ""), round(client.total_cost_jpy, 2)
