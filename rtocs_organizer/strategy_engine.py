# -*- coding: utf-8 -*-
"""一気通貫 企業戦略分析パイプライン。

企業名1つを入力に、8ステージ（会社→直近ニュース(英/日/中)→株式市場→業界・競合→
類似事例選定→他業種事例→課題→戦略策定）を順に実行し、結果dictを返す。
Streamlitには依存しない（ダッシュボードからもテストからも呼べる）。

- 各ステージは失敗しても {"error": ...} を格納して続行する（部分レポート方針）
- コストは既存organizerと同じ方式（トークン→USD→円換算）で集計
- ディープモード: gemini-2.5-pro + 戦略批判・改訂パス追加

Gemini API呼び出しは共通クライアント（../common/gemini_client.py、submodule
ochi1216/gemini-common-tools）のgenerate_advanced()経由で行う。会社PCでの
Gemini API直接アクセス遮断時、自宅PC経由プロキシへ自動フォールバックするため。
Google Search Grounding・JSONモードのペイロード組み立て・レスポンス解析ロジックは
従来のgoogle-genai/google-generativeai SDK使用時から変更していない
（GEMINI_MIGRATION_HANDOVER.md参照）。
"""

import os
import sys
import json
import re
from datetime import datetime

_COMMON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)
from gemini_client import generate_advanced

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
    ("market", "③ 株式市場分析"),
    ("industry", "④ 業界・競合分析"),
    ("retrieve", "⑤ 類似RTOCS事例の選定"),
    ("cases", "⑥ 他業種事例分析"),
    ("issues", "⑦ 課題分析"),
    ("strategy", "⑧ 戦略策定"),
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


def _extract_text(response):
    """generate_advanced()が返す生レスポンスdictから本文テキストを取り出す"""
    try:
        return response["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return ""


class GeminiClient:
    """JSONモード呼び出し＋コスト集計のラッパー。

    Gemini API呼び出しは共通クライアント(../common/gemini_client.py)の
    generate_advanced(payload, model=...)経由で行う。直接アクセス失敗時は
    自宅PC経由プロキシへ自動フォールバックする（呼び出し側はどちらの経路か
    意識しなくてよい）。
    """

    def __init__(self, api_key=None, model_name="gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self.total_cost_usd = 0.0
        self.stage_costs_jpy = {}

    @property
    def total_cost_jpy(self):
        return self.total_cost_usd * USD_JPY

    def _add_cost(self, stage, response):
        usage = response.get("usageMetadata", {}) if isinstance(response, dict) else {}
        t_in = usage.get("promptTokenCount", 0) or 0
        t_out = usage.get("candidatesTokenCount", 0) or 0
        p_in, p_out = MODEL_PRICING.get(self.model_name, MODEL_PRICING["gemini-2.5-flash"])
        cost = (t_in / 1_000_000 * p_in) + (t_out / 1_000_000 * p_out)
        self.total_cost_usd += cost
        self.stage_costs_jpy[stage] = self.stage_costs_jpy.get(stage, 0.0) + cost * USD_JPY

    def generate_json(self, prompt, stage="misc", retries=1):
        """JSONモードで呼び出しdictを返す。失敗時はValueError"""
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY が設定されていません。")
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        last_err = None
        for _ in range(retries + 1):
            try:
                response = generate_advanced(payload, model=self.model_name)
                self._add_cost(stage, response)
                text = _extract_text(response)
                if not text:
                    raise ValueError("空の応答")
                return json.loads(_strip_code_fence(text))
            except Exception as e:
                last_err = e
        raise ValueError(f"Gemini呼び出し失敗: {last_err}")

    def generate_grounded_json(self, prompt, stage="misc", retries=1):
        """Google Search Groundingを有効にした呼び出し。

        グラウンディングとJSONモード(responseMimeType)は併用できないため、
        プロンプト側にJSON形式での出力を指示し、コードフェンス除去＋json.loadsでパースする。
        """
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY が設定されていません。")
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
        }
        last_err = None
        for _ in range(retries + 1):
            try:
                response = generate_advanced(payload, model=self.model_name)
                self._add_cost(stage, response)
                text = _extract_text(response)
                if not text:
                    raise ValueError("空の応答")
                return json.loads(_strip_code_fence(text))
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

    def run_pipeline(self, company_name):
        stages = {}
        result = {
            "company": company_name,
            "mode": "deep" if self.deep else "flash",
            "model": self.model_name,
            "generated_at": datetime.now().isoformat(),
            "stages": stages,
            "market_data": None,
            "selected_case_records": [],
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

        target_summary_dict = {k: s1.get(k) for k in
                                ("official_name", "industry_sector", "business_model",
                                 "strengths", "weaknesses") if k in s1} if "error" not in s1 else {}
        if "error" not in news_stage and news_stage.get("recent_news"):
            target_summary_dict["recent_news_headlines"] = [
                f"[{n.get('date','')}/{n.get('language','')}] {n.get('headline','')}"
                for n in news_stage["recent_news"][:8]
            ]
        target_summary = json.dumps(target_summary_dict, ensure_ascii=False) if target_summary_dict else company_name

        # ③ 株式市場分析（yfinance実データ→Gemini解釈。未上場はスキップ）
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

        # ④ 業界・競合分析
        self._run_stage("industry", labels["industry"], lambda: self.client.generate_json(
            P.STAGE3_INDUSTRY.format(company=company_name,
                                     sector=s1.get("industry_sector", "不明"),
                                     stage1_summary=target_summary),
            stage="industry"), stages)

        # ⑤ 類似RTOCS事例の選定（LLM-as-retriever）
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

        # ⑤ 他業種事例分析（選定ケースのフルJSONを読み込み深掘り）
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

        # ⑦ 課題分析
        self._run_stage("issues", labels["issues"], lambda: self.client.generate_json(
            P.STAGE6_ISSUES.format(company=company_name, all_analysis=_all_analysis()),
            stage="issues"), stages)

        # ⑧ 戦略策定（ディープモードは批判・改訂パス付き）
        def stage7():
            lessons = json.dumps(stages.get("cases", {}), ensure_ascii=False)
            draft = self.client.generate_json(
                P.STAGE7_STRATEGY.format(company=company_name,
                                         all_analysis=_all_analysis(), lessons=lessons),
                stage="strategy")
            if self.deep:
                try:
                    revised = self.client.generate_json(
                        P.STAGE7B_CRITIQUE.format(company=company_name,
                                                  draft_strategy=json.dumps(draft, ensure_ascii=False),
                                                  all_analysis=_all_analysis()),
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
