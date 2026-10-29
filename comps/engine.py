"""Monta a tabela de comparáveis: junta dados da CVM (fundamentos) com preços (mercado)."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from .cvm import CVMRepository
from .financials import CompanyFinancials, Extractor
from .market import MarketCap, PriceProvider, Quote, market_cap
from .universe import Company, Universe

log = logging.getLogger(__name__)

MULTIPLES = ["EV/Receita", "EV/EBITDA", "EV/EBIT", "P/L", "EV/EBITDA ex-IFRS16", "Dív. Líq./EBITDA ex-IFRS16"]
STAT_COLS = MULTIPLES + ["Margem Bruta", "Margem EBITDA", "Margem Líquida", "Cresc. Receita"]


@dataclass
class CompsResult:
    target: str
    table: pd.DataFrame                       # uma linha por empresa (alvo primeiro)
    stats: pd.DataFrame                       # média e mediana dos peers
    companies: dict[str, Company]
    financials: dict[str, CompanyFinancials]
    quotes: dict[str, Quote | None]
    mcaps: dict[str, MarketCap | None]
    errors: dict[str, str] = field(default_factory=dict)
    renamed: dict[str, str] = field(default_factory=dict)   # ticker atual -> código pedido (antigo)
    ticker_notes: dict[str, str] = field(default_factory=dict)  # ticker -> correção de cadastro aplicada
    generated_at: str = field(default_factory=lambda: datetime.now().strftime("%d/%m/%Y %H:%M"))

    @property
    def target_ok(self) -> bool:
        """O alvo entrou na tabela? (pode ficar de fora se não tiver cotação ou dados na CVM)."""
        return not self.table.empty and self.table.iloc[0]["Papel"] == "Alvo"

    @property
    def target_row(self) -> pd.Series:
        return self.table.iloc[0]

    def warnings(self) -> dict[str, list[str]]:
        out = {}
        for t, fin in self.financials.items():
            w = list(fin.warnings)
            mc = self.mcaps.get(t)
            q = self.quotes.get(t)
            if q and q.source != "Yahoo Finance":
                w.append(f"Preço de {q.source}, de {q.as_of}")
            if q is not None and q.history is not None and len(q.history) > 20:
                ret = q.history.pct_change().dropna()
                if not ret.empty and ret.abs().max() > 0.25:
                    d = ret.abs().idxmax()
                    w.append(f"Salto de {ret[d]:+.0%} no preço em {d:%d/%m/%Y} (série do Yahoo): conferir se é "
                             "desdobramento/bonificação ou erro de dados; afeta o gráfico do one-pager")
            if mc and mc.scale_reason.startswith("regra"):
                w.append(f"Escala das ações definida por regra de bolso: ×{mc.scale_factor} (conferir)")
            if w:
                out[t] = w
        for new, old in self.renamed.items():
            if new not in self.ticker_notes:
                out.setdefault(new, []).append(f"Ticker {old} mudou para {new} (Formulário Cadastral da CVM)")
        for t, note in self.ticker_notes.items():
            out.setdefault(t, []).append(note)
        for t, e in self.errors.items():
            out.setdefault(t, []).append(f"EXCLUÍDA: {e}")
        return out


def _safe_div(a: float, b: float, cap: float | None = None) -> float:
    if b is None or b <= 0 or a is None or np.isnan(a):
        return np.nan
    v = a / b
    if cap is not None and (v < 0 or v > cap):
        return np.nan
    return v


def _row(ticker: str, comp: Company, fin: CompanyFinancials, quote: Quote, mc: MarketCap, role: str) -> dict:
    ltm = fin.ltm
    ev = mc.value_mm + fin.net_debt + fin.leases + fin.minorities           # pós-IFRS16 (com arrendamentos)
    ev_ex16 = mc.value_mm + fin.net_debt + fin.minorities                   # pré-IFRS16 (sem arrendamentos)
    ebitda_ex16 = ltm.ebitda - ltm.lease_payments
    return {
        "Ticker": ticker,
        "Empresa": comp.name.title().replace(" S.A.", "").replace(" S.a.", ""),
        "Papel": role,
        "Base": fin.basis,
        "Período": fin.ltm_label,
        "Preço (R$)": quote.price,
        "Data preço": quote.as_of,
        "Valor de Mercado": mc.value_mm,
        "Dívida Líquida": fin.net_debt,
        "Arrendamentos": fin.leases,
        "Minoritários": fin.minorities,
        "EV": ev,
        "Receita LTM": ltm.revenue,
        "Lucro Bruto LTM": ltm.gross_profit,
        "EBITDA LTM": ltm.ebitda,
        "EBIT LTM": ltm.ebit,
        "Lucro Líquido LTM": ltm.net_income,
        "Pagto. Arrend. LTM": ltm.lease_payments,
        "EBITDA ex-IFRS16 LTM": ebitda_ex16,
        "EV ex-IFRS16": ev_ex16,
        "Receita FY": fin.fy.revenue,
        "Receita FY-1": fin.fy_prev.revenue,
        "EV/Receita": _safe_div(ev, ltm.revenue),
        "EV/EBITDA": _safe_div(ev, ltm.ebitda),
        "EV/EBIT": _safe_div(ev, ltm.ebit),
        "P/L": _safe_div(mc.value_mm, ltm.net_income),
        "EV/EBITDA ex-IFRS16": _safe_div(ev_ex16, ebitda_ex16),
        "Dív. Líq./EBITDA ex-IFRS16": fin.net_debt / ebitda_ex16 if ebitda_ex16 > 0 else np.nan,
        "Margem Bruta": _safe_div(ltm.gross_profit, ltm.revenue) if ltm.gross_profit else np.nan,
        "Margem EBITDA": ltm.ebitda / ltm.revenue if ltm.revenue > 0 else np.nan,
        "Margem Líquida": ltm.net_income / ltm.revenue if ltm.revenue > 0 else np.nan,
        "Cresc. Receita": fin.fy.revenue / fin.fy_prev.revenue - 1 if fin.fy_prev.revenue > 0 else np.nan,
    }


def build_comps(target: str, peers: list[str], repo: CVMRepository | None = None,
                universe: Universe | None = None, prices: PriceProvider | None = None) -> CompsResult:
    repo = repo or CVMRepository()
    universe = universe or Universe(repo)
    prices = prices or PriceProvider()
    extractor = Extractor(repo)

    requested = [target] + list(peers)
    companies: dict[str, Company] = {}
    errors: dict[str, str] = {}
    renamed: dict[str, str] = {}
    notes: dict[str, str] = {}
    tickers: list[str] = []
    for raw in requested:
        t = raw.strip().upper().removesuffix(".SA")
        try:
            comp = universe.resolve(t)
        except KeyError as exc:
            errors[t] = str(exc)
            continue
        if comp.tickers and t not in comp.tickers.values():
            # Código antigo (ex.: GUAR3 -> RIAA3): usa o atual, senão a cotação pode vir parada
            renamed[comp.main_ticker] = t
            t = comp.main_ticker
        if t not in companies:          # sem duplicatas, mantendo a ordem (alvo primeiro)
            companies[t] = comp
            tickers.append(t)
            if comp.cnpj in universe.ticker_notes:
                notes[t] = universe.ticker_notes[comp.cnpj]
    if not tickers:
        return CompsResult(target.strip().upper(), pd.DataFrame(), pd.DataFrame(), {}, {}, {}, {}, errors)

    # Cotações em paralelo (rede); a leitura da CVM fica sequencial (pandas + cache compartilhado)
    needed = {tk for c in companies.values() for tk in c.tickers.values()} | set(companies)
    with ThreadPoolExecutor(max_workers=4) as pool:
        quotes = dict(zip(needed, pool.map(prices.quote, needed)))

    financials, mcaps, rows = {}, {}, []
    for t in tickers:
        if t not in companies:
            continue
        comp = companies[t]
        try:
            fin = extractor.extract(comp.cnpj, comp.name)
        except Exception as exc:  # noqa: BLE001 - uma empresa com problema não derruba a tabela
            log.exception("Falha ao extrair %s", t)
            errors[t] = f"dados CVM: {exc}"
            continue
        financials[t] = fin
        # O ticker pedido manda: se pediram a PN, o preço "de referência" é o da PN
        cls_tickers = dict(comp.tickers)
        quote = quotes.get(t) or quotes.get(comp.main_ticker) or next(
            (quotes[x] for x in cls_tickers.values() if quotes.get(x)), None)   # qualquer classe com cotação
        if quote is None:
            errors[t] = (f"sem cotação para {t}.SA no Yahoo Finance (e sem cache ou preço manual em "
                         "data/precos_manuais.csv)")
            continue
        mc = market_cap(fin.shares_on, fin.shares_pn, quotes, cls_tickers, fin.equity_controller)
        mcaps[t] = mc
        if mc is None or mc.value_mm <= 0:
            errors[t] = "não foi possível calcular o valor de mercado"
            continue
        rows.append(_row(t, comp, fin, quote, mc, "Alvo" if t == tickers[0] else "Peer"))

    table = pd.DataFrame(rows)
    if table.empty:
        return CompsResult(tickers[0], table, pd.DataFrame(), companies, financials, quotes, mcaps, errors, renamed, notes)
    peers_df = table[table["Papel"] == "Peer"]
    stats = pd.DataFrame(
        {"Média": peers_df[STAT_COLS].mean(numeric_only=True), "Mediana": peers_df[STAT_COLS].median(numeric_only=True)}
    ).T if not peers_df.empty else pd.DataFrame()
    return CompsResult(tickers[0], table, stats, companies, financials, quotes, mcaps, errors, renamed, notes)


def implied_valuation(result: CompsResult, multiple: str = "EV/EBITDA") -> dict | None:
    """Faixa de valor implícita para o alvo aplicando a mediana/quartis dos peers."""
    if result.table.empty or result.table.iloc[0]["Papel"] != "Alvo":
        return None
    tgt = result.table.iloc[0]
    peers = result.table[result.table["Papel"] == "Peer"][multiple].dropna()
    if len(peers) < 2:
        return None
    metric = {"EV/EBITDA": "EBITDA LTM", "EV/Receita": "Receita LTM", "EV/EBIT": "EBIT LTM",
              "P/L": "Lucro Líquido LTM", "EV/EBITDA ex-IFRS16": "EBITDA ex-IFRS16 LTM"}[multiple]
    bridge = tgt["EV"] - tgt["Valor de Mercado"] if multiple != "EV/EBITDA ex-IFRS16" else tgt["EV ex-IFRS16"] - tgt["Valor de Mercado"]
    out = {}
    for label, m in (("P25", peers.quantile(0.25)), ("Mediana", peers.median()), ("P75", peers.quantile(0.75))):
        value = m * tgt[metric]
        equity = value if multiple == "P/L" else value - bridge
        out[label] = {"múltiplo": m, "equity_mm": equity, "preço_por_ação": equity * 1e6 / result.mcaps[result.target].shares_total}
    out["preço_atual"] = tgt["Preço (R$)"]
    return out
