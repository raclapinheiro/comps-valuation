"""Preços de mercado e cálculo do valor de mercado.

Fonte primária: Yahoo Finance (biblioteca yfinance, tickers com sufixo .SA).
Para o demo não depender da internet, cada cotação obtida é salva em
data/prices_cache.json e reaproveitada se o Yahoo falhar (com aviso da data).
Também é possível forçar preços em data/precos_manuais.csv (ticker;preco;data).
"""
from __future__ import annotations

import json
import logging
import math
import warnings
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from .config import DATA_DIR

log = logging.getLogger(__name__)
# O yfinance ainda usa APIs que o pandas 3 marcou como obsoletas: os avisos são ruído para o usuário
warnings.filterwarnings("ignore", module=r"yfinance(\..*)?$")
warnings.filterwarnings("ignore", message=r".*inplace keyword.*")


@dataclass
class Quote:
    ticker: str
    price: float
    as_of: str
    source: str
    shares_hint: float | None = None          # nº de ações segundo o Yahoo (só para checar escala)
    history: pd.Series | None = field(default=None, repr=False)  # fechamentos de 12 meses


class PriceProvider:
    def __init__(self, data_dir: Path | str = DATA_DIR, use_yahoo: bool = True):
        self.data_dir = Path(data_dir)
        self.cache_path = self.data_dir / "prices_cache.json"
        self.manual_path = self.data_dir / "precos_manuais.csv"
        self.use_yahoo = use_yahoo
        self._cache = self._load_cache()
        self._manual = self._load_manual()

    def _load_cache(self) -> dict:
        try:
            return json.loads(self.cache_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _load_manual(self) -> dict:
        if not self.manual_path.exists():
            return {}
        df = pd.read_csv(self.manual_path, sep=";", dtype=str)
        return {r["ticker"].upper(): (float(r["preco"].replace(",", ".")), r.get("data", "")) for _, r in df.iterrows()}

    def _save_cache(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache, indent=1))

    def quote(self, ticker: str) -> Quote | None:
        t = ticker.upper()
        if t in self._manual:
            price, d = self._manual[t]
            return Quote(t, price, d or date.today().isoformat(), "manual (precos_manuais.csv)")
        if self.use_yahoo:
            q = self._yahoo(t)
            if q is None:                      # o Yahoo às vezes limita pedidos em sequência: tenta de novo uma vez
                import time
                time.sleep(1.5)
                q = self._yahoo(t)
            if q:
                hist = q.history
                self._cache[t] = {
                    "price": q.price, "as_of": q.as_of, "shares": q.shares_hint,
                    "history": {k.strftime("%Y-%m-%d"): float(v) for k, v in hist.items()} if hist is not None else {},
                }
                self._save_cache()
                return q
        if t in self._cache:
            c = self._cache[t]
            hist = pd.Series(c.get("history", {}), dtype=float)
            hist.index = pd.to_datetime(hist.index)
            return Quote(t, c["price"], c["as_of"], "cache local (Yahoo indisponível)", c.get("shares"), hist)
        return None

    @staticmethod
    def _yahoo(ticker: str) -> Quote | None:
        try:
            import yfinance as yf
        except ImportError:
            log.warning("yfinance não instalado")
            return None
        try:
            tk = yf.Ticker(f"{ticker}.SA")
            hist = tk.history(period="1y", auto_adjust=False)
            if hist.empty:
                return None
            close = hist["Close"].dropna()
            close.index = close.index.tz_localize(None)
            shares = None
            try:
                shares = float(tk.fast_info["shares"] or 0) or None
            except Exception:  # noqa: BLE001 - campo opcional, só para checagem
                shares = None
            return Quote(ticker, float(close.iloc[-1]), close.index[-1].strftime("%Y-%m-%d"), "Yahoo Finance",
                         shares, close)
        except Exception as exc:  # noqa: BLE001 - rede/HTTP/parse: cai para o cache
            log.warning("Yahoo falhou para %s: %s", ticker, exc)
            return None


# ---------------------------------------------------------------------- valor de mercado
@dataclass
class MarketCap:
    value_mm: float
    shares_total: float                 # quantidade de ações em unidades (já com escala resolvida)
    scale_factor: int                   # 1 ou 1000
    scale_reason: str
    detail: str
    on_shares: float = 0.0              # unidades
    pn_shares: float = 0.0
    on_price: float = 0.0
    pn_price: float = 0.0


def resolve_share_scale(shares_reported: float, price: float, equity_mm: float,
                        shares_hint: float | None) -> tuple[int, str]:
    """A CVM publica a quantidade de ações ora em unidades, ora em milhares, sem indicar a escala.

    Ex. (ITR 2T26): Lojas Renner informa 1.006.845 (milhares) e Grupo Mateus 2.302.987.204 (unidades).
    Decisão, nesta ordem:
      1) nº de ações do Yahoo, quando existir: escolhe a escala mais próxima;
      2) P/VPA plausível (entre 0,05x e 50x) com uma escala e não com a outra;
      3) regra de bolso: menos de 10 milhões de ações reportadas -> está em milhares.
    """
    if shares_reported <= 0:
        return 1, "sem ações reportadas"
    if shares_hint and shares_hint > 0:
        best = min((1, 1000), key=lambda f: abs(math.log(shares_reported * f / shares_hint)))
        return best, f"comparado com nº de ações do Yahoo ({shares_hint:,.0f})"
    if equity_mm > 0 and price > 0:
        ok = [f for f in (1, 1000) if 0.05 <= (shares_reported * f * price / 1e6) / equity_mm <= 50]
        if len(ok) == 1:
            return ok[0], "P/VPA plausível só nesta escala"
    f = 1000 if shares_reported < 10_000_000 else 1
    return f, "regra: < 10 milhões de ações reportadas => milhares"


def market_cap(shares_on: float, shares_pn: float, quotes: dict[str, Quote | None],
               tickers: dict[str, str], equity_mm: float) -> MarketCap | None:
    """Valor de mercado = Σ (ações da classe × preço da classe).

    Se a classe PN não tiver cotação própria, usa o preço da ON (aviso no detalhe).
    """
    q_on = quotes.get(tickers.get("ON", ""))
    q_pn = quotes.get(tickers.get("PN", ""))
    q_unit = quotes.get(tickers.get("UNIT", ""))
    ref = q_on or q_pn or q_unit
    if ref is None:
        return None
    total_reported = shares_on + shares_pn
    factor, reason = resolve_share_scale(total_reported, ref.price, equity_mm, ref.shares_hint)
    on, pn = shares_on * factor, shares_pn * factor

    parts, value = [], 0.0
    p_on = (q_on or ref).price
    p_pn = (q_pn or ref).price
    if on:
        p = p_on
        value += on * p
        parts.append(f"ON {on / 1e6:,.1f} mi × R$ {p:,.2f}" + ("" if q_on else " (preço de outra classe)"))
    if pn:
        p = p_pn
        value += pn * p
        parts.append(f"PN {pn / 1e6:,.1f} mi × R$ {p:,.2f}" + ("" if q_pn else " (preço de outra classe)"))
    return MarketCap(value / 1e6, on + pn, factor, reason, " + ".join(parts), on, pn, p_on, p_pn)


# ---------------------------------------------------------------------- beta
@dataclass
class Beta:
    raw: float
    adjusted: float          # ajuste de Blume: 0,67 × beta bruto + 0,33 × 1
    n_weeks: int
    source: str


def weekly_beta(ticker: str, index: str = "^BVSP", years: int = 2) -> Beta | None:
    """Beta da ação contra o Ibovespa com retornos semanais de 2 anos (padrão de mercado).

    O ajuste de Blume puxa o beta em direção a 1, porque betas extremos tendem a voltar
    para a média. Retorna None se o Yahoo não responder (a interface usa beta 1,0)."""
    try:
        import yfinance as yf
        px = {}
        for t in (f"{ticker}.SA", index):
            h = yf.Ticker(t).history(period=f"{years}y", interval="1wk", auto_adjust=True)["Close"].dropna()
            h.index = h.index.tz_localize(None).normalize()
            px[t] = h
        df = pd.concat(px, axis=1, join="inner").pct_change().dropna()
        if len(df) < 52:
            return None
        cov = df.cov().iloc[0, 1]
        raw = float(cov / df.iloc[:, 1].var())
        adj = 0.67 * raw + 0.33
        return Beta(raw, adj, len(df), f"regressão semanal de {len(df)} semanas contra o Ibovespa (Yahoo), ajuste de Blume")
    except Exception as exc:  # noqa: BLE001
        log.warning("Beta indisponível para %s: %s", ticker, exc)
        return None
