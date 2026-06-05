"""Extract a flat, typed feature dict from raw_data + dimensions.

This is the SINGLE source of truth that all investor criteria check against.
Any rule should only reference keys that exist here, never touch raw_data directly.

Usage:
    features = extract_features(raw_data, dimensions)
    # features is a dict with ~60 normalized fields
    # feature names are stable — criteria can check them safely
"""
from __future__ import annotations

import re
from typing import Any


def _f(v, default=0.0) -> float:
    """Safe float extraction."""
    if v is None:
        return default
    try:
        s = str(v).strip().replace(",", "").replace("%", "").replace("+", "").replace("¥", "").replace("亿", "")
        if not s or s in ("-", "—", "None", "nan", "N/A"):
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def _pct_change(values: list, n: int = 1) -> float:
    """n-period % change between first and last."""
    if not values or len(values) < 2:
        return 0.0
    last = _f(values[-1])
    earlier = _f(values[-1 - n]) if len(values) > n else _f(values[0])
    if earlier == 0:
        return 0.0
    return (last - earlier) / abs(earlier) * 100


def _avg(values: list, default: float = 0.0) -> float:
    vals = [_f(v) for v in values if _f(v) > 0]
    return sum(vals) / len(vals) if vals else default


def _last(values: list, default: float = 0.0) -> float:
    if not values:
        return default
    return _f(values[-1], default)


def _min(values: list, default: float = 0.0) -> float:
    vals = [_f(v) for v in values if _f(v) != 0]
    return min(vals) if vals else default


def extract_features(raw: dict, dims: dict) -> dict:
    """Extract ~60 features for criteria evaluation.

    Every feature has a STABLE key name. Never rename without updating
    investor_criteria.py.
    """
    f: dict[str, Any] = {}
    dim_data = raw.get("dimensions", {}) if raw else {}

    def _dd(key: str) -> dict:
        return (dim_data.get(key) or {}).get("data") or {}

    basic = _dd("0_basic")
    fin = _dd("1_financials")
    kline = _dd("2_kline")
    macro = _dd("3_macro")
    peers = _dd("4_peers")
    chain = _dd("5_chain")
    research = _dd("6_research")
    industry = _dd("7_industry")
    materials = _dd("8_materials")
    futures = _dd("9_futures")
    valuation = _dd("10_valuation")
    gov = _dd("11_governance")
    capital = _dd("12_capital_flow")
    policy = _dd("13_policy")
    moat = _dd("14_moat")
    events = _dd("15_events")
    lhb = _dd("16_lhb")
    sentiment = _dd("17_sentiment")
    trap = _dd("18_trap")
    contests = _dd("19_contests")

    # ─────────────── BASIC / PRICE ───────────────
    f["code"] = basic.get("code") or raw.get("ticker")
    f["name"] = basic.get("name") or "—"
    f["industry"] = basic.get("industry") or "—"
    f["price"] = _f(basic.get("price"))
    f["change_pct"] = _f(basic.get("change_pct"))
    f["market_cap_yi"] = _f(str(basic.get("market_cap", "0")).replace("亿", ""))
    f["circulating_cap_yi"] = _f(str(basic.get("circulating_cap", "0")).replace("亿", ""))
    f["listed_date"] = str(basic.get("listed_date", ""))[:10]
    f["chairman"] = basic.get("chairman") or "—"
    f["actual_controller"] = basic.get("actual_controller") or "—"
    f["staff_num"] = _f(basic.get("staff_num"))

    # ─────────────── FINANCIALS ───────────────
    roe_hist = fin.get("roe_history") or []
    rev_hist = fin.get("revenue_history") or []
    np_hist = fin.get("net_profit_history") or []
    div_years = fin.get("dividend_years") or []
    div_amounts = fin.get("dividend_amounts") or []

    f["roe_latest"] = _last(roe_hist)
    f["roe_5y_avg"] = _avg(roe_hist[-5:]) if len(roe_hist) >= 2 else _last(roe_hist)
    f["roe_5y_min"] = _min(roe_hist[-5:]) if len(roe_hist) >= 2 else _last(roe_hist)
    f["roe_5y_above_15"] = sum(1 for v in roe_hist[-5:] if _f(v) > 15)
    f["roe_5y_above_10"] = sum(1 for v in roe_hist[-5:] if _f(v) > 10)
    f["roe_trend_up"] = _last(roe_hist) > _avg(roe_hist[:-1]) if len(roe_hist) >= 3 else False

    f["revenue_latest_yi"] = _last(rev_hist)
    f["revenue_growth_latest"] = _pct_change(rev_hist, 1)
    f["revenue_growth_3y_cagr"] = ((_last(rev_hist) / _f(rev_hist[-4])) ** (1/3) - 1) * 100 if len(rev_hist) >= 4 and _f(rev_hist[-4]) > 0 else 0

    f["net_profit_latest_yi"] = _last(np_hist)
    f["net_profit_growth_latest"] = _pct_change(np_hist, 1)
    f["net_profit_5y_positive"] = sum(1 for v in np_hist[-5:] if _f(v) > 0)
    f["consecutive_profit_years"] = len([v for v in np_hist if _f(v) > 0])

    # Net margin (derived: np / revenue)
    if _last(rev_hist) > 0 and _last(np_hist) > 0:
        f["net_margin"] = round(_last(np_hist) / _last(rev_hist) * 100, 1)
    else:
        # Try from raw
        nm_raw = fin.get("net_margin")
        f["net_margin"] = _f(nm_raw) if nm_raw else 0

    # Financial health
    health = fin.get("financial_health") or {}
    f["current_ratio"] = _f(health.get("current_ratio"))
    f["debt_ratio"] = _f(health.get("debt_ratio"))
    f["fcf_margin"] = _f(health.get("fcf_margin"))
    f["roic"] = _f(health.get("roic"))
    f["fcf_positive"] = f["fcf_margin"] > 0

    # Dividend
    f["consecutive_dividend_years"] = len(div_years)
    f["dividend_yield"] = _f(basic.get("dividend_yield_ttm"))
    f["total_dividend_5y_per_10"] = sum(_f(v) for v in div_amounts[-5:])

    # ─────────────── K-LINE / TECHNICAL ───────────────
    f["stage"] = str(kline.get("stage", "—"))
    f["stage_num"] = 2 if "Stage 2" in f["stage"] else (1 if "Stage 1" in f["stage"] else 3 if "Stage 3" in f["stage"] else 4 if "Stage 4" in f["stage"] else 0)
    f["ma_align"] = str(kline.get("ma_align", "—"))
    f["ma_bull_aligned"] = "多头" in f["ma_align"]
    f["macd"] = str(kline.get("macd", "—"))
    f["macd_golden_cross"] = "金叉" in f["macd"] and "水上" in f["macd"]
    f["rsi"] = _f(kline.get("rsi"))
    f["rsi_overbought"] = f["rsi"] > 70
    f["rsi_oversold"] = f["rsi"] < 30

    stats = kline.get("kline_stats") or {}
    f["ytd_return"] = _f(stats.get("ytd_return"))
    f["volatility_1y"] = _f(stats.get("volatility"))
    f["max_drawdown_1y"] = _f(stats.get("max_drawdown"))

    # 52-week position
    candles = kline.get("candles_60d") or []
    if candles:
        closes = [_f(c.get("close")) for c in candles]
        highs = [_f(c.get("high")) for c in candles]
        lows = [_f(c.get("low")) for c in candles]
        if closes and highs and lows:
            f["pct_from_60d_high"] = (closes[-1] - max(highs)) / max(highs) * 100 if max(highs) > 0 else 0
            f["pct_from_60d_low"] = (closes[-1] - min(lows)) / min(lows) * 100 if min(lows) > 0 else 0

    # VCP hint (ranges contracting)
    f["vcp_hint"] = False  # would need full 6-month data

    # ─────────────── VALUATION ───────────────
    f["pe"] = _f(basic.get("pe_ttm")) or _f(valuation.get("pe"))
    f["pb"] = _f(basic.get("pb")) or _f(valuation.get("pb"))
    f["pe_x_pb"] = f["pe"] * f["pb"]
    # Parse "5 年 80 分位" → 80
    q_str = str(valuation.get("pe_quantile", ""))
    m = re.search(r"(\d+)", q_str)
    f["pe_quantile_5y"] = int(m.group(1)) if m else 50
    f["industry_pe"] = _f(valuation.get("industry_pe"))
    f["pe_vs_industry"] = (f["pe"] - f["industry_pe"]) / f["industry_pe"] * 100 if f["industry_pe"] > 0 else 0
    f["dcf_intrinsic_yi"] = 0
    dcf_str = str(valuation.get("dcf", ""))
    m = re.search(r"([\d\.]+)", dcf_str)
    if m:
        f["dcf_intrinsic_yi"] = float(m.group(1))
    f["safety_margin"] = (f["dcf_intrinsic_yi"] - f["market_cap_yi"]) / f["market_cap_yi"] * 100 if f["market_cap_yi"] > 0 else 0

    # ─────────────── PEERS ───────────────
    peer_table = peers.get("peer_table") or []
    peer_pes = [_f(p.get("pe")) for p in peer_table if not p.get("is_self") and _f(p.get("pe")) > 0]
    f["peers_count"] = len(peer_table)
    f["peer_avg_pe"] = sum(peer_pes) / len(peer_pes) if peer_pes else 0
    f["vs_peer_avg_pe"] = (f["pe"] - f["peer_avg_pe"]) / f["peer_avg_pe"] * 100 if f["peer_avg_pe"] > 0 else 0
    f["is_industry_leader"] = False  # needs more data
    # industry ranking (if peers sorted by market cap)
    if peer_table:
        self_idx = next((i for i, p in enumerate(peer_table) if p.get("is_self")), -1)
        f["industry_rank"] = self_idx + 1 if self_idx >= 0 else 0

    # ─────────────── RESEARCH (SELL-SIDE) ───────────────
    f["research_coverage"] = _f(research.get("coverage_count")) or _f(research.get("report_count"))
    f["buy_rating_pct"] = _f(research.get("buy_rating_pct"))
    f["target_price_avg"] = _f(research.get("target_price_avg"))
    f["consensus_eps_2026"] = _f(research.get("consensus_eps_2026"))
    f["consensus_pe_2026"] = _f(research.get("consensus_pe_2026"))
    # Upside vs current
    if f["price"] > 0 and f["target_price_avg"] > 0:
        f["upside_to_target"] = (f["target_price_avg"] - f["price"]) / f["price"] * 100
    else:
        f["upside_to_target"] = 0
    # Forward growth implied by 2026 forecast vs 2024 EPS
    eps_latest = _f(basic.get("eps"))
    if eps_latest > 0 and f["consensus_eps_2026"] > 0:
        f["consensus_growth_to_2026"] = (f["consensus_eps_2026"] / eps_latest - 1) * 100
    else:
        f["consensus_growth_to_2026"] = 0

    # ─────────────── INDUSTRY ───────────────
    f["industry_growth_pct"] = _f(industry.get("growth"))
    f["industry_lifecycle"] = str(industry.get("lifecycle", "—"))
    f["industry_is_growing"] = "成长" in f["industry_lifecycle"]
    f["industry_in_decline"] = "衰退" in f["industry_lifecycle"]

    # ─────────────── CAPITAL FLOW ───────────────
    # v2.2: 主力资金替代北向（北向已关停）
    _main_flow = capital.get("main_fund_flow_20d") or []
    _main_5d_net = 0
    if _main_flow:
        for _rec in _main_flow[:5]:
            try:
                _main_5d_net += float((_rec.get("主力净流入-净额", 0) if isinstance(_rec, dict) else 0) or 0)
            except (ValueError, TypeError):
                pass
    f["main_fund_5d_net_yi"] = round(_main_5d_net / 1e8, 2)
    f["main_fund_net_positive"] = _main_5d_net > 0
    # 保留兼容旧名 (一些 investor_criteria 规则可能引用)
    f["northbound_20d_yi"] = f["main_fund_5d_net_yi"]
    f["northbound_net_positive"] = f["main_fund_net_positive"]
    f["margin_trend"] = str(capital.get("margin_trend", "—"))
    f["holders_trend"] = str(capital.get("holders_trend", "—"))
    f["holders_concentrating"] = "降" in f["holders_trend"]  # 户数下降 = 筹码集中
    f["unlock_pressure_12m"] = len(capital.get("unlock_schedule") or [])

    # ─────────────── GOVERNANCE ───────────────
    pledge = gov.get("pledge") or []
    f["has_pledge_issue"] = len(pledge) > 0 and any(_f(str(p.get("质押比例", 0))) > 30 for p in pledge if isinstance(p, dict))
    insider = gov.get("insider_trades_1y") or []
    f["insider_net_buy"] = len(insider) > 0
    f["no_violations"] = True

    # ─────────────── MOAT ───────────────
    moat_scores = moat.get("scores") or {}
    f["moat_intangible"] = _f(moat_scores.get("intangible"))
    f["moat_switching"] = _f(moat_scores.get("switching"))
    f["moat_network"] = _f(moat_scores.get("network"))
    f["moat_scale"] = _f(moat_scores.get("scale"))
    f["moat_total"] = f["moat_intangible"] + f["moat_switching"] + f["moat_network"] + f["moat_scale"]
    f["moat_clear"] = f["moat_total"] >= 24  # avg 6+/10

    # ─────────────── EVENTS ───────────────
    timeline = events.get("event_timeline") or []
    f["recent_events_count"] = len(timeline)
    text = " ".join(timeline).lower()
    f["has_positive_catalyst"] = any(kw in text for kw in ["预告", "增长", "大订单", "新品", "合作", "并购"])
    f["has_negative_catalyst"] = any(kw in text for kw in ["亏损", "下修", "处罚", "诉讼", "风险"])

    # ─────────────── LHB ───────────────
    f["lhb_30d_count"] = _f(lhb.get("lhb_count_30d"))
    f["matched_youzi"] = lhb.get("matched_youzi") or []
    f["matched_youzi_count"] = len(f["matched_youzi"])
    inst_vs = lhb.get("inst_vs_youzi") or {}
    f["inst_net_buy_lhb"] = _f(inst_vs.get("institutional_net"))
    f["youzi_net_buy_lhb"] = _f(inst_vs.get("youzi_net"))

    # ─────────────── SENTIMENT ───────────────
    f["sentiment_heat"] = _f(sentiment.get("thermometer_value"))
    f["sentiment_positive_pct"] = _f(sentiment.get("positive_pct"))
    f["sentiment_label"] = str(sentiment.get("sentiment_label", "中性"))

    # ─────────────── TRAP ───────────────
    f["trap_signals_hit"] = _f(trap.get("signals_hit_count")) or 0
    f["trap_level"] = str(trap.get("trap_level", "🟢 安全"))
    f["is_safe"] = "安全" in f["trap_level"]

    # ─────────────── CONTESTS ───────────────
    summary = contests.get("summary") or {}
    f["xq_cube_count"] = _f(summary.get("xueqiu_cubes_total"))
    f["xq_high_return_count"] = _f(summary.get("high_return_cubes"))

    # ─────────────── FUND MANAGERS (抄作业) ───────────────
    fms = raw.get("fund_managers") or []
    f["fund_manager_count"] = len(fms)
    if fms:
        returns = [_f(m.get("return_5y")) for m in fms]
        f["fund_manager_max_5y_return"] = max(returns) if returns else 0
        f["has_top_fund_holder"] = any(_f(m.get("return_5y")) > 100 for m in fms)
    else:
        f["fund_manager_max_5y_return"] = 0
        f["has_top_fund_holder"] = False

    # ─────────────── MACRO ───────────────
    f["macro_rate_cycle"] = str(macro.get("rate_cycle", "中性"))
    f["macro_rate_easing"] = "利好" in f["macro_rate_cycle"] or "降息" in f["macro_rate_cycle"] or "宽松" in f["macro_rate_cycle"]
    f["macro_commodity"] = str(macro.get("commodity", "中性"))

    # ─────────────── POLICY ───────────────
    f["policy_supportive"] = "积极" in str(policy.get("policy_dir", ""))
    f["policy_tightening"] = "收紧" in str(policy.get("policy_dir", ""))

    # ─────────────── FIN MODELS SUPPORT (for DCF/Comps/LBO) ───────────────
    # Shares outstanding in 亿股 — derived from market_cap / price
    mcap = _f(f.get("market_cap_yi"), 0)
    px = _f(f.get("price"), 0)
    f["shares_outstanding_yi"] = round(mcap / px, 3) if px > 0 else 0
    # EPS = net_income / shares
    latest_ni = _last(fin.get("net_profit_history") or [])
    f["eps"] = round(latest_ni / f["shares_outstanding_yi"], 3) if f["shares_outstanding_yi"] > 0 else 0
    # BVPS = equity / shares
    eq = _f(f.get("equity_yi"), 0)
    f["bvps"] = round(eq / f["shares_outstanding_yi"], 3) if f["shares_outstanding_yi"] > 0 else 0
    # FCF latest (proxy from net_income × 0.8 if not present)
    f["fcf_latest_yi"] = round(latest_ni * 0.8, 2) if latest_ni > 0 else 0
    # EBITDA (proxy: net_income / 0.6)
    f["ebitda_yi"] = round(latest_ni / 0.6, 2) if latest_ni > 0 else 0
    # Debt and cash (from financial_health if available; else default)
    health = fin.get("financial_health") or {}
    f["total_debt_yi"] = _f(health.get("total_debt"), 0) if isinstance(health, dict) else 0
    f["cash_yi"] = _f(health.get("cash"), 0) if isinstance(health, dict) else 0
    # Gross margin (%)
    f["gross_margin"] = _f(fin.get("gross_margin"), default=f.get("net_margin", 10) + 18)
    # PS ratio
    rev = f.get("revenue_latest_yi", 0)
    f["ps"] = round(mcap / rev, 2) if rev > 0 else 0
    # v2.12.1 · 真实计算 industry_growth 和 market_share（原版硬编 default=10 → BCG 永远 Dog）

    # industry_growth: 从 industry.growth 文本 regex 解析百分比
    # industry.growth 可能是 "25%/年"/"+30%"/"25"/字典{growth:"25%"} 等格式
    _growth_raw = industry.get("growth")
    if isinstance(_growth_raw, (int, float)):
        f["industry_growth"] = float(_growth_raw)
    elif isinstance(_growth_raw, str):
        _gm = re.search(r"([+\-]?\d{1,3}(?:\.\d+)?)\s*%", _growth_raw)
        f["industry_growth"] = float(_gm.group(1)) if _gm else 0.0
    else:
        f["industry_growth"] = 0.0

    # market_share: 真实 = 公司市值 / 行业总市值 × 100
    # 数据源：basic.market_cap (亿) + industry.cninfo_metrics.total_mcap_yi (亿)
    _cmcap_yi = _f(basic.get("market_cap_yi")) or _f(basic.get("market_cap"))
    _imcap_yi = _f((industry.get("cninfo_metrics") or {}).get("total_mcap_yi"))
    if _cmcap_yi > 0 and _imcap_yi > 0:
        f["market_share"] = round(_cmcap_yi / _imcap_yi * 100, 2)
    else:
        f["market_share"] = 0.0
    # Dividend yield from valuation/basic
    f["dividend_yield"] = _f(valuation.get("dividend_yield"), default=0)
    # PEG
    peg_val = f.get("pe", 0) / f.get("rev_growth_3y", 1) if f.get("rev_growth_3y", 0) > 0 else 99
    f["peg"] = round(peg_val, 2)
    # Gross margin trend flag
    f["gross_margin_expanding"] = False  # default; could be computed from hist
    # Ticker passthrough
    f["ticker"] = raw.get("ticker", "") if raw else ""
    # Market: infer from ticker suffix
    ticker_str = f["ticker"]
    if ticker_str.endswith(".SZ") or ticker_str.endswith(".SH"):
        f["market"] = "A"
    elif ticker_str.endswith(".HK"):
        f["market"] = "HK"
    else:
        f["market"] = "US"

    # ─────────────── AI 卡位 / 瓶颈点 (Serenity · H 组) ───────────────
    # v3.6.3 · Serenity「AI 产业链卡脖子」派生特征。
    # 四因子合成 ai_chokepoint_score(0-100)：AI 链命中 × 不可替代性 × 小盘弹性 × 需求拐点。
    # 不在 AI 链上 → 直接腰斩到接近 0（Serenity 不碰）。
    import json as _json
    try:
        _chain_txt = _json.dumps(chain, ensure_ascii=False) if chain else ""
        _ind_txt = _json.dumps(industry, ensure_ascii=False) if isinstance(industry, dict) else str(industry)
    except (TypeError, ValueError):
        _chain_txt, _ind_txt = "", ""
    _blob = " ".join([
        str(f.get("industry", "")), str(f.get("name", "")),
        _chain_txt, _ind_txt, text,  # `text` = 事件 timeline (已 lower)
    ]).lower()
    _AI_CHOKEPOINT_KW = [
        # 数据中心光 / 先进封装 / 化合物半导体 / 互连 / 算力
        "光模块", "光芯片", "cpo", "光引擎", "硅光", "光通信", "光器件", "激光器", "eml", "vcsel",
        "hbm", "cowos", "先进封装", "封装基板", "abf", "载板",
        "inp", "磷化铟", "砷化镓", "化合物半导体", "衬底", "外延", "晶体生长",
        "pcb", "高速铜", "铜连接", "铜缆", "背板连接器", "连接器",
        "液冷", "散热", "电源", "bbu", "服务器电源", "pdu",
        "交换机", "算力", "ai 芯片", "asic", "gpu", "risc-v", "存储", "ddr",
        "ai server", "ai 服务器", "数据中心", "data center", "光纤", "空芯光纤",
        # AR/VR 近眼显示 + 消费/车载光学（AI 终端侧光学链）· 注意不用裸词 ar/vr 防误匹配
        "光学", "光电子", "光学元件", "光学薄膜", "光波导", "衍射光波导", "waveguide",
        "光栅", "滤光片", "镀膜", "棱镜", "微棱镜", "镜头", "摄像模组", "相机模组", "光学镜片",
        "增强现实", "虚拟现实", "混合现实", "头显", "近眼显示", "ar/vr", "ar 眼镜", "ar眼镜",
        "micro-led", "microled", "硅基oled", "车载光学", "衍射光学", "晶圆级光学",
        # v3.7.x · issue #72 · 具身智能 / 人形机器人卡位链
        # 「具身智能 = AI 的物理化」· Serenity 本人推过绿的谐波(谐波减速器) · 这些
        # 上游核心零部件同样符合"难替代 + 供给紧 + 没被定价"的卡脖子逻辑。
        "人形机器人", "具身智能", "humanoid", "人形", "机器人", "robot",
        "谐波减速器", "谐波减速", "谐波", "rv减速器", "rv 减速器", "减速器", "精密减速器",
        "行星滚柱丝杠", "滚柱丝杠", "行星滚柱", "丝杠", "滚珠丝杠", "梯形丝杠",
        "灵巧手", "dexterous", "机械臂", "机械手", "关节模组", "执行器", "actuator",
        "空心杯电机", "空心杯", "无框电机", "无框力矩电机", "伺服电机", "伺服系统",
        "六维力", "力传感器", "力矩传感器", "触觉传感器", "电子皮肤", "扭矩传感器",
    ]
    _ai_hit = [kw for kw in _AI_CHOKEPOINT_KW if kw in _blob]
    f["ai_chain_hit"] = len(_ai_hit) > 0
    f["ai_chain_keywords"] = _ai_hit[:8]
    # 不可替代性：切换成本 + 规模壁垒 (各 0-10 → 0-20)
    _irrepl = (f.get("moat_switching", 0) or 0) + (f.get("moat_scale", 0) or 0)
    f["ai_irreplaceable"] = _irrepl >= 12
    # 小盘弹性：市值越小越高
    _mc = f.get("market_cap_yi", 0) or 0
    if _mc <= 0:
        _elasticity = 0.5
    elif _mc < 100:
        _elasticity = 1.0
    elif _mc < 300:
        _elasticity = 0.8
    elif _mc < 800:
        _elasticity = 0.5
    elif _mc < 2000:
        _elasticity = 0.25
    else:
        _elasticity = 0.1
    f["ai_smallcap"] = 0 < _mc < 300
    # 需求拐点：政策支持 / 正向催化 / 行业高增
    _inflection = 0.0
    if f.get("policy_supportive"):
        _inflection += 0.4
    if f.get("has_positive_catalyst"):
        _inflection += 0.3
    if f.get("industry_growth", 0) >= 20:
        _inflection += 0.3
    _inflection = min(_inflection, 1.0)
    # 合成：AI 链是门槛
    if f["ai_chain_hit"]:
        _kw_strength = min(len(_ai_hit), 3) / 3.0     # 命中强度 0-1
        _irr_norm = min(_irrepl / 16.0, 1.0)          # 16/20 视作满格
        _score = (0.35 * _kw_strength + 0.30 * _irr_norm +
                  0.20 * _elasticity + 0.15 * _inflection) * 100
    else:
        _score = 8.0 * _elasticity                    # 不在链上 → 接近 0
    f["ai_chokepoint_score"] = round(_score, 1)

    return f


def summary(features: dict) -> str:
    """Human-readable summary for debugging."""
    lines = []
    lines.append(f"{features.get('name')} ({features.get('code')})")
    lines.append(f"  价格 ¥{features.get('price')} · 市值 {features.get('market_cap_yi')}亿 · 行业 {features.get('industry')}")
    lines.append(f"  PE {features.get('pe')} · PB {features.get('pb')} · PE 5Y分位 {features.get('pe_quantile_5y')}")
    lines.append(f"  ROE 最新 {features.get('roe_latest')}% · 5Y均 {features.get('roe_5y_avg'):.1f}% · 5Y>=15%: {features.get('roe_5y_above_15')}/5")
    lines.append(f"  营收增速 {features.get('revenue_growth_latest'):.1f}% · 净利率 {features.get('net_margin')}% · 负债率 {features.get('debt_ratio')}%")
    lines.append(f"  Stage {features.get('stage')} · MA多头 {features.get('ma_bull_aligned')} · RSI {features.get('rsi')}")
    lines.append(f"  研报覆盖 {features.get('research_coverage')} · 买入率 {features.get('buy_rating_pct')}% · 目标涨幅 {features.get('upside_to_target'):.1f}%")
    lines.append(f"  护城河 {features.get('moat_total')}/40 · 基金经理 {features.get('fund_manager_count')} · 杀猪盘 {features.get('trap_level')}")
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, ".")
    from lib.cache import read_task_output
    ticker = sys.argv[1] if len(sys.argv) > 1 else "002273.SZ"
    raw = read_task_output(ticker, "raw_data")
    dims = read_task_output(ticker, "dimensions")
    if raw and dims:
        features = extract_features(raw, dims)
        print(summary(features))
        print(f"\nTotal features: {len(features)}")
    else:
        print("raw_data.json or dimensions.json not found")
