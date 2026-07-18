# -*- coding: utf-8 -*-
"""一気通貫 企業戦略分析パイプライン。

企業名1つを入力に、10ステージ（会社→直近ニュース(英/日/中)→アナリスト洞察・経営陣メッセージ→
マクロ・技術トレンド→株式市場→業界・競合→類似事例選定→他業種事例→課題→戦略策定）を順に実行し、
結果dictを返す。Streamlitには依存しない（ダッシュボードからもテストからも呼べる）。

- 各ステージは失敗しても {"error": ...} を格納して続行する（部分レポート方針）
- コストは既存organizerと同じ方式（トークン→USD→円換算）で集計
- ディープモード: gemini-2.5-pro + 戦略批判・改訂パス追加
"""

import os
import json
import re
from datetime import datetime

import rtocs_index
import strategy_prompts as P

# 100万トークンあたりの単価（USD）: (入力, 出力)
MODEL_PRICING = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
}
USD_JPY = 160

STAGE_LABELS = [
    ("company", "① 会社分析"),
    ("news", "② 直近ニュース収集（英/日/中）"),
    ("analyst", "③ アナリスト洞察・経営陣メッセージ収集"),
    ("macro", "④ マクロ・技術トレンド分析"),
    ("market", "⑤ 株式市場分析"),
    ("industry", "⑥ 業界・競合分析"),
    ("retrieve", "⑦ 類似RTOCS事例の選定"),
    ("cases", "⑧ 他業種事例分析"),
    ("issues", "⑨ 課題分析"),
    ("strategy", "⑩ 戦略策定"),
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
    """JSONモード呼び出し＋コスト集計のラッパー"""

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
        `google_search`ツールとはAPI形状が異なり使えない（実機で400エラーを確認済み）。
        後継の統合SDK`google-genai`（別パッケージ、共存可能）のみがgoogle_searchツールを
        公開しているため、ニュース収集ステージに限りこちらを使う。
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


def fetch_market_data(ticker_candidates):
    """yfinanceで株価・財務データを取得する。全滅ならNone（=未上場扱い）。

    取得できないフィールドは黙って欠落させる（全フィールドがオプション）。
    """
    try:
        import yfinance as yf
    except ImportError:
        return None

    for ticker_symbol in ticker_candidates or []:
        try:
            t = yf.Ticker(ticker_symbol)
            hist = t.history(period="5y", interval="1mo")
            if hist is None or hist.empty:
                continue

            info = {}
            try:
                info = t.info or {}
            except Exception:
                pass

            closes = hist["Close"].dropna()
            price_history = [
                {"date": idx.strftime("%Y-%m"), "close": round(float(v), 2)}
                for idx, v in closes.items()
            ]

            financials = []
            try:
                fin = t.financials  # 年次: 行=科目, 列=決算期
                if fin is not None and not fin.empty:
                    for col in fin.columns:
                        entry = {"period": str(col)[:10]}
                        for label, key in [("Total Revenue", "revenue"), ("Net Income", "net_income")]:
                            if label in fin.index:
                                v = fin.loc[label, col]
                                if v == v:  # not NaN
                                    entry[key] = float(v)
                        financials.append(entry)
            except Exception:
                pass

            def _num(key):
                v = info.get(key)
                return float(v) if isinstance(v, (int, float)) else None

            return {
                "ticker": ticker_symbol,
                "currency": info.get("currency", ""),
                "market_cap": _num("marketCap"),
                "trailing_pe": _num("trailingPE"),
                "price_to_book": _num("priceToBook"),
                "dividend_yield": _num("dividendYield"),
                "fifty_two_week_high": _num("fiftyTwoWeekHigh"),
                "fifty_two_week_low": _num("fiftyTwoWeekLow"),
                "last_price": round(float(closes.iloc[-1]), 2),
                # 軸1-⑤: 財務の実行可能性データ（戦略提言の資金的な裏付けを判断するための材料）
                "total_cash": _num("totalCash"),
                "total_debt": _num("totalDebt"),
                "debt_to_equity": _num("debtToEquity"),
                "free_cash_flow": _num("freeCashflow"),
                "price_history": price_history,
                "financials": financials,
            }
        except Exception:
            continue
    return None


def _market_data_for_prompt(md):
    """プロンプト投入用に価格履歴を年次サマリーへ圧縮する"""
    slim = {k: v for k, v in md.items() if k != "price_history"}
    yearly = {}
    for p in md.get("price_history", []):
        yearly[p["date"][:4]] = p["close"]  # 各年の最終月終値が残る
    slim["yearly_close"] = yearly
    return json.dumps(slim, ensure_ascii=False)


class StrategyEngine:
    def __init__(self, api_key=None, deep=False, data_dir=None, progress_cb=None,
                 market_fetcher=fetch_market_data):
        self.deep = deep
        self.model_name = "gemini-2.5-pro" if deep else "gemini-2.5-flash"
        self.client = GeminiClient(api_key=api_key, model_name=self.model_name)
        self.data_dir = data_dir or rtocs_index.DEFAULT_DATA_DIR
        self.progress_cb = progress_cb or (lambda key, label, status: None)
        self.market_fetcher = market_fetcher

    def _run_stage(self, key, label, fn, stages):
        self.progress_cb(key, label, "start")
        try:
            stages[key] = fn()
            self.progress_cb(key, label, "done")
        except Exception as e:
            stages[key] = {"error": f"取得失敗: {e}"}
            self.progress_cb(key, label, "error")

    def run_pipeline(self, company_name, user_constraints=None):
        """user_constraints: 経営者自身が明示する制約条件（任意のフリーテキスト）。
        課題分析・戦略策定（ディープモードの改訂パス含む）に必ず反映させる。
        """
        stages = {}
        user_constraints = (user_constraints or "").strip()
        constraints_block = (
            f"\n# 経営者自身が明示した制約条件（必須順守）\n{user_constraints}\n"
            "上記の制約に反する分析・提言は絶対に行わないでください。\n"
        ) if user_constraints else ""
        result = {
            "company": company_name,
            "mode": "deep" if self.deep else "flash",
            "model": self.model_name,
            "generated_at": datetime.now().isoformat(),
            "stages": stages,
            "market_data": None,
            "selected_case_records": [],
            "user_constraints": user_constraints,
        }
        labels = dict(STAGE_LABELS)

        # ① 会社分析＋証券コード解決
        self._run_stage("company", labels["company"], lambda: self.client.generate_json(
            P.STAGE1_COMPANY.format(company=company_name), stage="company"), stages)
        s1 = stages.get("company", {})

        # ② 直近ニュース収集（英/日/中、Google Search Grounding）
        def stage_news():
            official = s1.get("official_name", company_name) if "error" not in s1 else company_name
            return self.client.generate_grounded_json(
                P.STAGE1B_NEWS.format(company=company_name, official_name=official),
                stage="news")
        self._run_stage("news", labels["news"], stage_news, stages)
        news_stage = stages.get("news", {})

        # ③ アナリスト洞察・経営陣メッセージ収集（英/日/中、Google Search Grounding）
        def stage_analyst():
            official = s1.get("official_name", company_name) if "error" not in s1 else company_name
            return self.client.generate_grounded_json(
                P.STAGE1C_ANALYST.format(company=company_name, official_name=official),
                stage="analyst")
        self._run_stage("analyst", labels["analyst"], stage_analyst, stages)
        analyst_stage = stages.get("analyst", {})

        # ④ マクロ・技術トレンド分析（業界全体・時代全体の構造変化。個社分析ではない）
        def stage_macro():
            return self.client.generate_grounded_json(
                P.STAGE1D_MACRO.format(company=company_name,
                                       sector=s1.get("industry_sector", "不明")),
                stage="macro")
        self._run_stage("macro", labels["macro"], stage_macro, stages)
        macro_stage = stages.get("macro", {})

        target_summary_dict = {k: s1.get(k) for k in
                                ("official_name", "industry_sector", "business_model",
                                 "strengths", "weaknesses") if k in s1} if "error" not in s1 else {}
        if user_constraints:
            target_summary_dict["user_constraints"] = user_constraints
        if "error" not in news_stage and news_stage.get("recent_news"):
            target_summary_dict["recent_news_headlines"] = [
                f"[{n.get('date','')}/{n.get('language','')}] {n.get('headline','')}"
                for n in news_stage["recent_news"][:8]
            ]
        if "error" not in analyst_stage:
            if analyst_stage.get("analyst_views"):
                target_summary_dict["analyst_views_summary"] = [
                    f"[{a.get('date','')}] {a.get('source','')}: {a.get('rating_or_view','')}"
                    for a in analyst_stage["analyst_views"][:5]
                ]
            if analyst_stage.get("market_expectation_gap"):
                target_summary_dict["market_expectation_gap"] = analyst_stage["market_expectation_gap"]
        if "error" not in macro_stage and macro_stage.get("macro_trends"):
            target_summary_dict["macro_trends_summary"] = [
                f"[{t.get('category','')}/{t.get('impact_direction','')}] {t.get('trend','')}"
                for t in macro_stage["macro_trends"][:6]
            ]
        target_summary = json.dumps(target_summary_dict, ensure_ascii=False) if target_summary_dict else company_name

        # ⑤ 株式市場分析（yfinance実データ→Gemini解釈。未上場はスキップ）
        def stage2():
            if "error" in s1:
                return {"skipped": "会社分析が失敗したためスキップ"}
            if not s1.get("is_listed"):
                return {"skipped": "未上場（または上場確認不可）のため定量分析をスキップ"}
            md = self.market_fetcher(s1.get("ticker_candidates", []))
            if not md:
                return {"skipped": "株価データを取得できなかったためスキップ（ティッカー未解決）"}
            result["market_data"] = md
            out = self.client.generate_json(
                P.STAGE2_MARKET.format(company=company_name,
                                       market_data=_market_data_for_prompt(md)),
                stage="market")
            return out
        self._run_stage("market", labels["market"], stage2, stages)

        # ⑥ 業界・競合分析
        self._run_stage("industry", labels["industry"], lambda: self.client.generate_json(
            P.STAGE3_INDUSTRY.format(company=company_name,
                                     sector=s1.get("industry_sector", "不明"),
                                     stage1_summary=target_summary),
            stage="industry"), stages)

        # ⑦ 類似RTOCS事例の選定（LLM-as-retriever）
        index = rtocs_index.build_index(data_dir=self.data_dir)
        records = index.get("records", [])

        def stage4():
            if not records:
                return {"skipped": "ケースライブラリが空のためスキップ"}
            out = self.client.generate_json(
                P.STAGE4_RETRIEVE.format(company=company_name,
                                         target_summary=target_summary,
                                         case_index=rtocs_index.compact_index_for_llm(records)),
                stage="retrieve")
            by_id = {r["video_id"]: r for r in records}
            result["selected_case_records"] = [
                by_id[c["video_id"]] for c in out.get("selected_cases", [])
                if c.get("video_id") in by_id
            ]
            return out
        self._run_stage("retrieve", labels["retrieve"], stage4, stages)

        # ⑧ 他業種事例分析（選定ケースのフルJSONを読み込み深掘り）
        def stage5():
            if not result["selected_case_records"]:
                return {"skipped": "類似事例が選定されなかったためスキップ"}
            details = []
            for rec in result["selected_case_records"]:
                full = rtocs_index.load_full_case(rec["video_id"], data_dir=self.data_dir)
                if not full:
                    continue
                content = full.get("content", full)
                details.append({
                    "company": rec["company"],
                    "episode": rec["episode"],
                    "gist": content.get("gist", ""),
                    "conclusion": content.get("conclusion", ""),
                    "main_point_categories": [mp.get("category", "")
                                              for mp in content.get("main_points", [])],
                    "next_actions": content.get("next_actions", []),
                })
            if not details:
                return {"skipped": "選定ケースの詳細データを読み込めませんでした"}
            return self.client.generate_json(
                P.STAGE5_CASES.format(company=company_name,
                                      target_summary=target_summary,
                                      case_details=json.dumps(details, ensure_ascii=False)),
                stage="cases")
        self._run_stage("cases", labels["cases"], stage5, stages)

        def _all_analysis():
            return json.dumps(
                {k: v for k, v in stages.items() if isinstance(v, dict) and "error" not in v},
                ensure_ascii=False)

        # ⑨ 課題分析
        self._run_stage("issues", labels["issues"], lambda: self.client.generate_json(
            P.STAGE6_ISSUES.format(company=company_name, all_analysis=_all_analysis(),
                                   user_constraints_block=constraints_block),
            stage="issues"), stages)

        # ⑩ 戦略策定（ディープモードは批判・改訂パス付き）
        def stage7():
            lessons = json.dumps(stages.get("cases", {}), ensure_ascii=False)
            draft = self.client.generate_json(
                P.STAGE7_STRATEGY.format(company=company_name, all_analysis=_all_analysis(),
                                         lessons=lessons, user_constraints_block=constraints_block),
                stage="strategy")
            if self.deep:
                try:
                    revised = self.client.generate_json(
                        P.STAGE7B_CRITIQUE.format(company=company_name,
                                                  draft_strategy=json.dumps(draft, ensure_ascii=False),
                                                  all_analysis=_all_analysis(),
                                                  user_constraints_block=constraints_block),
                        stage="strategy")
                    if revised.get("strategies"):
                        return revised
                except Exception:
                    pass  # 改訂に失敗しても初稿を採用
            return draft
        self._run_stage("strategy", labels["strategy"], stage7, stages)

        result["costs"] = {
            "stages_jpy": {k: round(v, 2) for k, v in self.client.stage_costs_jpy.items()},
            "total_usd": round(self.client.total_cost_usd, 4),
            "total_jpy": round(self.client.total_cost_jpy, 2),
        }
        return result


def generate_trend_commentary(records, api_key=None, model_name="gemini-2.5-flash"):
    """フェーズ1: ケースライブラリ全件の俯瞰総評を生成する。

    戻り値: (markdown文字列, コスト円)
    """
    client = GeminiClient(api_key=api_key, model_name=model_name)
    out = client.generate_json(
        P.TREND_COMMENTARY.format(case_index=rtocs_index.compact_index_for_llm(records)),
        stage="trend")
    return out.get("commentary_markdown", ""), round(client.total_cost_jpy, 2)
