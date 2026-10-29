"""Linha de comando: gera Excel de comps + one-pager.

Exemplos:
  python cli.py LREN3                                  # peers sugeridos (IA ou regra)
  python cli.py LREN3 --peers CEAB3 RIAA3 AZZA3 VIVA3  # peers definidos à mão
  python cli.py LREN3 --check                          # só imprime os números (sem gerar arquivos)
  python cli.py LREN3 --peers CEAB3 RIAA3 --dcf --tese "A margem volta a subir com a nova logística"
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

import pandas as pd

from comps.ai import describe_business, suggest_peers
from comps.config import OUTPUT_DIR
from comps.cvm import CVMRepository
from comps.engine import build_comps, implied_valuation
from comps.excel import export_excel
from comps.market import PriceProvider
from comps.onepager import export_onepager
from comps.universe import Universe
from comps.excel_model import export_model
from comps.valuation import build_valuation, summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Trading comps automáticos a partir de dados da CVM")
    ap.add_argument("target", help="ticker da empresa-alvo, ex.: LREN3")
    ap.add_argument("--peers", nargs="*", help="tickers dos peers (se omitido, sugere automaticamente)")
    ap.add_argument("--n-peers", type=int, default=8)
    ap.add_argument("--offline", action="store_true", help="usa só arquivos já baixados em data/")
    ap.add_argument("--check", action="store_true", help="só imprime a tabela, sem gerar arquivos")
    ap.add_argument("--dcf", action="store_true", help="também roda o valuation por teses (DCF + football field)")
    ap.add_argument("--tese", action="append", default=[], help="uma tese de investimento (pode repetir)")
    ap.add_argument("--teses-arquivo", help="arquivo .txt com uma tese por linha")
    ap.add_argument("--beta", type=float, help="beta informado (senão calcula contra o Ibovespa)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    print("Carregando dados da CVM (o primeiro download leva ~1 min)…")
    repo = CVMRepository(offline=args.offline)
    universe = Universe(repo)
    target = universe.resolve(args.target)

    if args.peers:
        peers = args.peers
    else:
        sugg = suggest_peers(target, universe, args.n_peers)
        peers = [p.ticker for p in sugg]
        print("\nPeers sugeridos:")
        for p in sugg:
            print(f"  {p.ticker:7s} {p.name[:40]:40s} {p.reason}")

    res = build_comps(args.target, peers, repo, universe, PriceProvider())
    if not res.target_ok:
        print(f"Não foi possível calcular {res.target}: {res.errors.get(res.target, 'motivo não identificado')}")
        return 1

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    cols = ["Ticker", "Período", "Valor de Mercado", "EV", "Receita LTM", "EBITDA LTM", "Margem EBITDA",
            "EV/EBITDA", "P/L", "EV/EBITDA ex-IFRS16"]
    print("\n", res.table[cols].round(2).to_string(index=False))
    print("\nMediana dos peers:\n", res.stats.loc[["Mediana"], ["EV/Receita", "EV/EBITDA", "P/L"]].round(2).to_string())
    for t, ws in res.warnings().items():
        for w in ws:
            print(f"  [aviso] {t}: {w}")
    val = implied_valuation(res)
    if val:
        print(f"\nValor implícito por ação (EV/EBITDA dos peers): P25 R$ {val['P25']['preço_por_ação']:.2f} | "
              f"mediana R$ {val['Mediana']['preço_por_ação']:.2f} | P75 R$ {val['P75']['preço_por_ação']:.2f} "
              f"| atual R$ {val['preço_atual']:.2f}")
    if args.check:
        return 0

    stamp = date.today().strftime("%Y%m%d")
    xlsx = export_excel(res, OUTPUT_DIR / f"comps_{res.target}_{stamp}.xlsx")
    bullets, source = describe_business(target)
    val = None
    files = [xlsx]
    if args.dcf:
        theses = list(args.tese)
        if args.teses_arquivo:
            theses += [l.strip() for l in open(args.teses_arquivo, encoding="utf-8") if l.strip()]
        print("\nValuation por teses:" + ("".join(f"\n  {i + 1}. {t}" for i, t in enumerate(theses)) or " (sem teses: regra simples)"))
        val = build_valuation(res, theses, beta=args.beta)
        print(f"  Premissas: {val.assumptions_source} · WACC {val.wacc.value:.1%} (beta {val.wacc.beta:.2f})")
        print(f"  Preço-alvo (DCF base): R$ {val.target_price:.2f} · upside {val.upside:+.1%} · recomendação: {val.recommendation}")
        print(summary(val).round(3).to_string())
        for w in val.warnings:
            print(f"  [aviso] {w}")
        files.append(export_model(val, OUTPUT_DIR / f"modelo_{res.target}_{stamp}.xlsx", comps=res))
    pptx = export_onepager(res, OUTPUT_DIR / f"onepager_{res.target}_{stamp}.pptx", bullets, source, valuation=val)
    files.append(pptx)
    print("\nArquivos gerados:\n  " + "\n  ".join(str(f) for f in files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
