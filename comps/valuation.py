"""Orquestra o valuation da empresa-alvo: teses -> premissas -> DCF -> football field."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import pandas as pd

from .ai import propose_assumptions
from .dcf import (MARKET_DEFAULTS, SCENARIOS, Base, DcfResult, FieldRow, Scenario, Wacc, check_ordering,
                  default_scenarios, football_field, historical_base, run_dcf, sensitivity, validate)
from .engine import CompsResult, implied_valuation
from .market import Beta, weekly_beta

log = logging.getLogger(__name__)

# Critério de recomendação (mesmo da aba DCF do Excel, onde é editável)
BUY_UPSIDE = 0.15     # COMPRA se o upside do preço-alvo for de pelo menos +15%
SELL_UPSIDE = -0.05   # VENDA se for de -5% ou pior; entre os dois, NEUTRO


def recommendation(upside: float, buy: float = BUY_UPSIDE, sell: float = SELL_UPSIDE) -> str:
    if upside != upside:   # NaN
        return "SEM RECOMENDAÇÃO"
    if upside >= buy:
        return "COMPRA"
    if upside <= sell:
        return "VENDA"
    return "NEUTRO"


@dataclass
class ValuationResult:
    ticker: str
    company: str
    price: float
    price_date: str
    shares: float
    base: Base
    theses: list[str]
    scenarios: dict[str, Scenario]
    assumptions_source: str
    wacc: Wacc
    beta: Beta | None
    dcf: dict[str, DcfResult]
    sens: pd.DataFrame
    comps_ranges: dict[str, dict | None]
    field: list[FieldRow]
    minorities: float
    history: pd.DataFrame = field(default_factory=pd.DataFrame)
    warnings: list[str] = field(default_factory=list)

    @property
    def target_price(self) -> float:
        """Preço-alvo = valor por ação do DCF no cenário base."""
        return self.dcf["base"].per_share if "base" in self.dcf else float("nan")

    @property
    def upside(self) -> float:
        return self.target_price / self.price - 1 if self.price else float("nan")

    @property
    def recommendation(self) -> str:
        return recommendation(self.upside)


def history_table(res: CompsResult) -> pd.DataFrame:
    """Histórico que ancora as premissas (e que é mandado à IA junto com as teses)."""
    fin = res.financials[res.target]
    rows = {}
    for label, p in ((f"FY{int(fin.fy_label[2:]) - 1:02d}", fin.fy_prev), (f"FY{fin.fy_label[2:]}", fin.fy),
                     (fin.ltm_label, fin.ltm)):
        e16 = p.ebitda - p.lease_payments
        rows[label] = {
            "Receita": p.revenue,
            "EBITDA ex-IFRS16": e16,
            "Margem EBITDA ex-IFRS16": e16 / p.revenue if p.revenue else float("nan"),
            "Capex": p.capex,
            "Capex/receita": p.capex / p.revenue if p.revenue else float("nan"),
            "Lucro líquido": p.net_income,
        }
    df = pd.DataFrame(rows)
    fy, prev = fin.fy.revenue, fin.fy_prev.revenue
    df.loc["Crescimento da receita (FY)"] = [float("nan"), fy / prev - 1 if prev else float("nan"), float("nan")]
    df.loc["Capital de giro/receita"] = [float("nan"), float("nan"),
                                         fin.working_capital / fin.ltm.revenue if fin.ltm.revenue else float("nan")]
    return df


def _hist_text(df: pd.DataFrame) -> str:
    lines = []
    for idx, row in df.iterrows():
        vals = []
        for col, v in row.items():
            if pd.isna(v):
                continue
            vals.append(f"{col}: {v:.1%}" if ("/" in idx or "Margem" in idx or "Crescimento" in idx) else f"{col}: {v:,.0f}")
        if vals:
            lines.append(f"- {idx}: " + "; ".join(vals))
    return "\n".join(lines)


def build_valuation(res: CompsResult, theses: list[str] | None = None,
                    scenarios: dict[str, Scenario] | None = None, market: dict | None = None,
                    beta: float | None = None, use_ai: bool = True, fetch_beta: bool = True) -> ValuationResult:
    t = res.target
    fin, mc = res.financials[t], res.mcaps[t]
    if not res.target_ok:
        raise ValueError(f"{t} não entrou na tabela de comps: {res.errors.get(t, 'sem dados')}")
    quote = res.quotes.get(t) or res.quotes.get(res.companies[t].main_ticker) or next(
        (res.quotes[x] for x in res.companies[t].tickers.values() if res.quotes.get(x)), None)
    mkt = {**MARKET_DEFAULTS, **(market or {})}
    theses = [x.strip() for x in (theses or []) if x and x.strip()]
    warnings: list[str] = []

    base = historical_base(fin)
    defaults = default_scenarios(base, mkt["g"])
    hist = history_table(res)

    source = "regra simples (sem teses)" if not theses else "regra simples (sem IA)"
    if scenarios is None:
        scenarios = defaults
        if theses and use_ai:
            ref = {"crescimento_base": defaults["base"].growth, "margem_base": defaults["base"].margin,
                   "capex_pct": defaults["base"].capex_pct, "nwc_pct": defaults["base"].nwc_pct}
            proposed, source = propose_assumptions(res.companies[t], _hist_text(hist), theses, ref)
            if proposed:
                scenarios = {
                    k: Scenario(name=k, growth=v["growth"], margin=v["margin"], capex_pct=v["capex_pct"],
                                da_pct=defaults[k].da_pct, nwc_pct=v["nwc_pct"], terminal_growth=mkt["g"],
                                rationale=v["rationale"], theses_used=v["theses_used"], source=source)
                    for k, v in proposed.items()
                }
    else:
        source = "premissas editadas pelo analista"

    for k in list(scenarios):
        scenarios[k], w = validate(scenarios[k], base)
        warnings += w
    warnings += check_ordering(scenarios)

    b = weekly_beta(t) if (beta is None and fetch_beta) else None
    beta_val = beta if beta is not None else (b.adjusted if b else 1.0)
    beta_src = "informado pelo analista" if beta is not None else (b.source if b else "1,0 (padrão: Yahoo indisponível)")
    if beta is None and b is None:
        warnings.append("Beta não calculado (Yahoo sem histórico semanal): usando 1,0")
    wacc = Wacc(rf=mkt["rf"], beta=beta_val, erp=mkt["erp"], kd_pre=mkt.get("kd_pre", mkt["rf"] + mkt["kd_spread"]),
                tax=mkt["tax"], equity_value=mc.value_mm, net_debt=fin.net_debt, beta_source=beta_src)

    shares, price = mc.shares_total, quote.price
    dcf = {k: run_dcf(base, scenarios[k], wacc, fin.minorities, shares, price) for k in SCENARIOS if k in scenarios}
    for r in dcf.values():
        warnings += r.warnings
    sens = sensitivity(base, scenarios["base"], wacc, fin.minorities, shares, price) if "base" in scenarios else pd.DataFrame()

    comps_ranges = {"EV/EBITDA": implied_valuation(res, "EV/EBITDA"), "P/L": implied_valuation(res, "P/L")}
    rows = football_field(comps_ranges, dcf, quote.history, price)
    if base.capex == 0:
        warnings.append("Capex não identificado no DFC: premissa de capex usa o mínimo de 0,5% da receita")
    return ValuationResult(t, res.target_row["Empresa"], price, quote.as_of, shares, base, theses, scenarios, source,
                           wacc, b, dcf, sens, comps_ranges, rows, fin.minorities, hist,
                           list(dict.fromkeys(warnings)))


def summary(v: ValuationResult) -> pd.DataFrame:
    rows = {}
    for k, r in v.dcf.items():
        s = r.scenario
        rows[k] = {"Crescimento médio": sum(s.growth) / len(s.growth), "Margem EBITDA média": sum(s.margin) / len(s.margin),
                   "WACC": r.wacc, "g perpetuidade": s.terminal_growth, "EV (R$ mi)": r.ev, "Equity (R$ mi)": r.equity,
                   "Valor por ação (R$)": r.per_share, "Upside": r.upside,
                   "% do EV na perpetuidade": r.tv_share if not math.isnan(r.tv_share) else float("nan")}
    return pd.DataFrame(rows)
