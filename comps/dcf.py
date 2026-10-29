"""DCF guiado por teses.

Fluxo: histórico da CVM -> premissas por cenário (propostas pela IA a partir das teses,
ou por regra simples) -> validação -> fluxo de caixa livre da firma (FCFF) de 5 anos ->
valor terminal (Gordon) -> EV -> valor por ação -> football field junto com os comps.

Convenção ex-IFRS 16 (a mais usada em varejo no Brasil): o aluguel é tratado como despesa
operacional. Assim:
  * EBITDA ex-IFRS16 = EBITDA contábil - pagamentos de arrendamento (principal + juros);
  * a dívida de arrendamento NÃO entra na ponte EV -> equity;
  * a D&A usada para o imposto exclui a depreciação do direito de uso.
Tudo consistente: o aluguel já saiu do fluxo, então não pode sair de novo como dívida.

Desconto no fim de cada ano (end-year). Valores em R$ milhões.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .financials import CompanyFinancials

YEARS = 5
SCENARIOS = ("pessimista", "base", "otimista")

# Premissas de mercado padrão (editáveis na interface e no Excel). Fontes no README e na aba WACC.
MARKET_DEFAULTS = {
    "rf": 0.1125,     # média da Selic esperada no Focus (23/10/2026) para o fim de 2026-2029: 13,25 / 11,75 / 10,00 / 10,00
    "erp": 0.0423,    # prêmio de risco de mercado implícito (Damodaran, jan/2026); o risco-país já está na taxa em reais
    "kd_spread": 0.015,  # spread de crédito sobre a taxa livre de risco, para o custo da dívida antes do IR
    "tax": 0.34,      # IR + CSLL, alíquota nominal
    "g": 0.045,       # crescimento nominal na perpetuidade: inflação de longo prazo (~3,7% no Focus) + ~1% real
}

# Limites de sanidade para premissas (vindas da IA ou digitadas)
LIMITS = {
    "growth": (-0.30, 0.50),
    "margin_delta": 0.15,          # margem EBITDA até 15 p.p. acima ou abaixo da histórica
    "margin": (-0.10, 0.60),
    "capex_pct": (0.0, 0.25),
    "da_pct": (0.0, 0.25),
    "nwc_pct": (-0.50, 1.00),
    "g": (0.0, 0.07),
}


# ---------------------------------------------------------------------- dados de partida
@dataclass
class Base:
    """Ano-base do modelo (LTM) e indicadores históricos que ancoram as premissas."""
    label: str
    revenue: float
    ebitda_ex16: float
    capex: float
    da: float
    nwc: float
    growth_fy: float          # crescimento da receita no último ano fechado
    margin_fy_prev: float     # margem EBITDA ex-IFRS16 do ano anterior (para ver tendência)
    tax_effective: float

    @property
    def margin(self) -> float:
        return self.ebitda_ex16 / self.revenue if self.revenue else 0.0

    @property
    def capex_pct(self) -> float:
        return self.capex / self.revenue if self.revenue else 0.0

    @property
    def nwc_pct(self) -> float:
        return self.nwc / self.revenue if self.revenue else 0.0


def historical_base(fin: CompanyFinancials) -> Base:
    ltm, fy, prev = fin.ltm, fin.fy, fin.fy_prev
    growth = fy.revenue / prev.revenue - 1 if prev.revenue > 0 else 0.0
    m_prev = (prev.ebitda - prev.lease_payments) / prev.revenue if prev.revenue > 0 else 0.0
    tax_eff = -ltm.taxes / ltm.ebt if ltm.ebt > 0 else MARKET_DEFAULTS["tax"]
    return Base(
        label=fin.ltm_label,
        revenue=ltm.revenue,
        ebitda_ex16=ltm.ebitda - ltm.lease_payments,
        capex=ltm.capex,
        da=ltm.da,
        nwc=fin.working_capital,
        growth_fy=growth,
        margin_fy_prev=m_prev,
        tax_effective=min(max(tax_eff, 0.0), 0.5),
    )


# ---------------------------------------------------------------------- premissas
@dataclass
class Scenario:
    name: str
    growth: list[float]              # crescimento da receita, ano 1..5
    margin: list[float]              # margem EBITDA ex-IFRS16, ano 1..5
    capex_pct: float                 # capex / receita
    da_pct: float                    # D&A sem direito de uso / receita (base do benefício fiscal)
    nwc_pct: float                   # capital de giro / receita
    terminal_growth: float
    rationale: dict[str, str] = field(default_factory=dict)   # driver -> justificativa (ligada às teses)
    theses_used: list[int] = field(default_factory=list)
    source: str = "regra simples"

    def as_frame(self) -> pd.DataFrame:
        cols = [f"Ano {i + 1}" for i in range(YEARS)]
        return pd.DataFrame([self.growth, self.margin], index=["Crescimento da receita", "Margem EBITDA ex-IFRS16"],
                            columns=cols)


def default_scenarios(base: Base, g: float = MARKET_DEFAULTS["g"]) -> dict[str, Scenario]:
    """Sem IA: o crescimento parte do último ano e converge linearmente para o de longo prazo;
    a margem fica na do LTM. Otimista/pessimista = +-3 p.p. de crescimento e +-1,5 p.p. de margem."""
    start = float(np.clip(base.growth_fy, -0.10, 0.25))
    long_run = g + 0.01
    path = [start + (long_run - start) * (i + 1) / YEARS for i in range(YEARS)]
    capex = float(np.clip(base.capex_pct, 0.005, 0.15))
    nwc = float(np.clip(base.nwc_pct, *LIMITS["nwc_pct"]))
    out = {}
    for name, dg, dm in (("pessimista", -0.03, -0.015), ("base", 0.0, 0.0), ("otimista", 0.03, 0.015)):
        out[name] = Scenario(
            name=name,
            growth=[round(x + dg, 4) for x in path],
            margin=[round(base.margin + dm, 4)] * YEARS,
            capex_pct=round(capex, 4), da_pct=round(capex, 4), nwc_pct=round(nwc, 4),
            terminal_growth=g,
            rationale={"crescimento": "Parte do crescimento do último ano e converge para inflação + 1% real",
                       "margem": "Mantém a margem EBITDA ex-IFRS16 do LTM",
                       "capex": "Capex/receita do LTM; D&A igual ao capex (estado estável)",
                       "capital de giro": "Capital de giro/receita do último balanço"},
        )
    return out


def validate(s: Scenario, base: Base) -> tuple[Scenario, list[str]]:
    """Aplica limites de sanidade. Nada é descartado em silêncio: todo ajuste vira aviso."""
    w = []

    def clip(v, lo, hi, what):
        c = float(min(max(v, lo), hi))
        if abs(c - v) > 1e-9:
            w.append(f"{s.name}: {what} {v:.1%} fora do limite, ajustado para {c:.1%}".replace(".", ","))
        return c

    s.growth = [clip(x, *LIMITS["growth"], f"crescimento do ano {i + 1}") for i, x in enumerate(s.growth)]
    lo_m = max(LIMITS["margin"][0], base.margin - LIMITS["margin_delta"])
    hi_m = min(LIMITS["margin"][1], base.margin + LIMITS["margin_delta"])
    s.margin = [clip(x, lo_m, hi_m, f"margem do ano {i + 1}") for i, x in enumerate(s.margin)]
    s.capex_pct = clip(s.capex_pct, *LIMITS["capex_pct"], "capex/receita")
    s.da_pct = clip(s.da_pct, *LIMITS["da_pct"], "D&A/receita")
    s.nwc_pct = clip(s.nwc_pct, *LIMITS["nwc_pct"], "capital de giro/receita")
    s.terminal_growth = clip(s.terminal_growth, *LIMITS["g"], "crescimento na perpetuidade")
    return s, w


def check_ordering(scen: dict[str, Scenario]) -> list[str]:
    """O otimista precisa valer mais que o base, e o base mais que o pessimista (em média)."""
    w = []
    avg = {k: (np.mean(v.growth), np.mean(v.margin)) for k, v in scen.items()}
    if {"pessimista", "base", "otimista"} <= avg.keys():
        for i, what in ((0, "crescimento"), (1, "margem")):
            if not avg["pessimista"][i] <= avg["base"][i] <= avg["otimista"][i]:
                w.append(f"Ordem dos cenários invertida no {what} médio (pessimista ≤ base ≤ otimista)")
    return w


# ---------------------------------------------------------------------- WACC
@dataclass
class Wacc:
    rf: float
    beta: float
    erp: float
    kd_pre: float
    tax: float
    equity_value: float       # valor de mercado
    net_debt: float           # dívida líquida sem arrendamentos (ex-IFRS16)
    beta_source: str = "padrão"

    @property
    def ke(self) -> float:
        return self.rf + self.beta * self.erp

    @property
    def kd(self) -> float:
        return self.kd_pre * (1 - self.tax)

    @property
    def wd(self) -> float:
        d = max(self.net_debt, 0.0)   # caixa líquido não vira peso negativo
        return d / (d + self.equity_value) if (d + self.equity_value) > 0 else 0.0

    @property
    def value(self) -> float:
        return (1 - self.wd) * self.ke + self.wd * self.kd


# ---------------------------------------------------------------------- DCF
@dataclass
class DcfResult:
    scenario: Scenario
    table: pd.DataFrame        # linhas = itens do fluxo; colunas = Base, Ano 1..5
    wacc: float
    pv_fcff: float
    terminal_value: float
    pv_terminal: float
    ev: float
    equity: float
    per_share: float
    upside: float
    warnings: list[str] = field(default_factory=list)

    @property
    def tv_share(self) -> float:
        return self.pv_terminal / self.ev if self.ev else float("nan")


def run_dcf(base: Base, s: Scenario, wacc: Wacc, minorities: float, shares: float, price: float,
            r_override: float | None = None) -> DcfResult:
    w = []
    r = wacc.value if r_override is None else r_override
    g = s.terminal_growth
    rev = [base.revenue]
    for x in s.growth:
        rev.append(rev[-1] * (1 + x))
    rev = np.array(rev)
    margin = np.array([base.margin] + list(s.margin))
    ebitda = rev * margin
    da = rev * s.da_pct
    ebit = ebitda - da
    taxes = np.maximum(ebit, 0) * wacc.tax
    capex = rev * s.capex_pct
    nwc = rev * s.nwc_pct
    d_nwc = np.concatenate([[0.0], np.diff(nwc)])
    fcff = ebitda - taxes - capex - d_nwc
    t = np.arange(0, YEARS + 1)
    disc = 1 / (1 + r) ** t
    pv = fcff * disc

    cols = ["Base"] + [f"Ano {i}" for i in range(1, YEARS + 1)]
    table = pd.DataFrame(
        [rev, np.concatenate([[np.nan], s.growth]), ebitda, margin, da, ebit, -taxes, -capex, nwc, -d_nwc, fcff,
         np.concatenate([[np.nan], disc[1:]]), np.concatenate([[np.nan], pv[1:]])],
        index=["Receita", "Crescimento", "EBITDA ex-IFRS16", "Margem EBITDA", "D&A (sem direito de uso)", "EBIT",
               "(-) IR/CS sobre EBIT", "(-) Capex", "Capital de giro", "(-) Variação do capital de giro",
               "Fluxo de caixa livre (FCFF)", "Fator de desconto", "Valor presente do FCFF"],
        columns=cols,
    )
    if r <= g:
        w.append(f"WACC ({r:.1%}) menor ou igual ao crescimento na perpetuidade ({g:.1%}): valor terminal não existe")
        tv = pv_tv = float("nan")
    else:
        tv = fcff[-1] * (1 + g) / (r - g)
        pv_tv = tv * disc[-1]
        if r - g < 0.03:
            w.append(f"WACC - g de só {r - g:.1%}: o valor fica muito sensível às premissas de longo prazo")
    pv_sum = float(pv[1:].sum())
    ev = pv_sum + pv_tv
    equity = ev - wacc.net_debt - minorities
    per_share = equity * 1e6 / shares if shares > 0 else float("nan")
    res = DcfResult(s, table, r, pv_sum, tv, pv_tv, ev, equity, per_share,
                    per_share / price - 1 if price > 0 else float("nan"), w)
    if not math.isnan(res.tv_share) and res.tv_share > 0.85:
        w.append(f"{s.name}: {res.tv_share:.0%} do EV vem da perpetuidade; o modelo depende muito do longo prazo")
    if fcff[1:].min() < 0:
        w.append(f"{s.name}: fluxo de caixa livre negativo em algum ano da projeção")
    return res


def sensitivity(base: Base, s: Scenario, wacc: Wacc, minorities: float, shares: float, price: float,
                d_wacc=(-0.01, -0.005, 0.0, 0.005, 0.01), d_g=(-0.01, -0.005, 0.0, 0.005, 0.01)) -> pd.DataFrame:
    """Valor por ação variando WACC (linhas) e crescimento na perpetuidade (colunas)."""
    out = {}
    for dg in d_g:
        col = {}
        s2 = Scenario(**{**s.__dict__, "terminal_growth": s.terminal_growth + dg})
        for dw in d_wacc:
            r = wacc.value + dw
            col[round(r, 4)] = run_dcf(base, s2, wacc, minorities, shares, price, r_override=r).per_share
        out[round(s.terminal_growth + dg, 4)] = col
    df = pd.DataFrame(out)
    df.index.name, df.columns.name = "WACC", "g"
    return df


# ---------------------------------------------------------------------- football field
@dataclass
class FieldRow:
    label: str
    low: float
    high: float
    mid: float | None = None
    kind: str = "comps"        # comps | dcf | mercado


def football_field(comps_ranges: dict[str, dict], dcf: dict[str, DcfResult], hist: pd.Series | None,
                   price: float) -> list[FieldRow]:
    rows = []
    for label, v in comps_ranges.items():
        if v:
            rows.append(FieldRow(f"Comps: {label} (P25–P75)", v["P25"]["preço_por_ação"], v["P75"]["preço_por_ação"],
                                 v["Mediana"]["preço_por_ação"], "comps"))
    vals = [r.per_share for r in dcf.values() if not math.isnan(r.per_share)]
    if vals:
        base = dcf.get("base")
        rows.append(FieldRow("DCF (pessimista–otimista)", min(vals), max(vals),
                             base.per_share if base else None, "dcf"))
    if hist is not None and len(hist) > 20:
        rows.append(FieldRow("Cotação 12 meses (mín.–máx.)", float(hist.min()), float(hist.max()), price,
                             "mercado"))
    return rows
