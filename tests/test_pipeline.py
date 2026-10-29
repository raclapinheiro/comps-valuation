"""Testes do pipeline com números reais (DFP 2025 + ITR 2T26) de 4 varejistas.

Rodar:  python -m pytest -q
Os valores esperados foram conferidos à mão contra os arquivos da CVM.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from comps.cvm import CVMRepository
from comps.engine import build_comps, implied_valuation
from comps.financials import Extractor
from comps.market import PriceProvider, resolve_share_scale
from comps.universe import Universe
from tests.build_fixture import build

PRICES = "ticker;preco;data\nGMAT3;7,00;2026-10-28\nASAI3;9,00;2026-10-28\nRIAA3;10,00;2026-10-28\nVIVA3;25,00;2026-10-28\n"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("cvm")
    build(d)
    (d / "precos_manuais.csv").write_text(PRICES)
    repo = CVMRepository(d, offline=True)
    return repo, Universe(repo), PriceProvider(d, use_yahoo=False)


def approx(x, y, tol=0.01):
    return math.isclose(x, y, abs_tol=tol)


def test_universe_resolves_tickers(env):
    _, uni, _ = env
    assert uni.resolve("GMAT3").name == "GRUPO MATEUS S.A."
    assert uni.resolve("asai3.sa").cnpj == "06.057.223/0001-71"
    assert "GMAT9" not in uni.by_ticker  # ticker encerrado é ignorado
    # mudança de ticker: o código antigo ainda acha a empresa, mas o atual é o RIAA3
    assert uni.resolve("GUAR3").main_ticker == "RIAA3"
    # data fim == data início é erro de cadastro: o papel continua valendo
    assert uni.resolve("VIVA3").main_ticker == "VIVA3"


def test_mateus_ltm_and_leases_inside_debt(env):
    repo, uni, _ = env
    fin = Extractor(repo).extract(uni.resolve("GMAT3").cnpj, "Mateus")
    assert fin.basis == "consolidado" and fin.ltm_label == "LTM 2T26"
    # Receita LTM = FY25 + 6M26 - 6M25 (a linha de trimestre isolado 9.999.999 deve ser ignorada)
    assert approx(fin.ltm.revenue, 38424.403 + 19254.731 - 17110.941)
    assert approx(fin.ltm.ebit, 2260.989 + 888.511 - 1143.036)
    assert approx(fin.ltm.da, 539.596 + 336.139 - 218.387)
    assert approx(fin.ltm.net_income, 1857.293 + 449.686 - 662.439)  # FY sem 3.11.01 -> usa 3.11
    assert approx(fin.leases, 218.167 + 375.363)
    assert approx(fin.leases_in_debt, fin.leases)                    # arrendamento estava dentro de 2.01.04/2.02.01
    assert approx(fin.debt_ex_leases, 1529.728 + 1194.648 - 593.530)
    assert approx(fin.net_debt, fin.debt_ex_leases - 1631.590)
    assert approx(fin.minorities, 1160.623)
    assert approx(fin.ltm.lease_payments, 492.404 + 301.311 - 208.669)


def test_sendas_individual_only(env):
    repo, uni, _ = env
    fin = Extractor(repo).extract(uni.resolve("ASAI3").cnpj, "Assaí")
    assert fin.basis == "individual"
    assert approx(fin.ltm.revenue, 77307 + 37813 - 37554)
    assert approx(fin.ltm.ebitda, (3623 + 2704 - 1934) + (1755 + 927 - 866))
    assert approx(fin.leases, 511 + 10200) and fin.leases_in_debt == 0
    assert approx(fin.ltm.lease_payments, (325 + 1146) + (165 + 641) - (161 + 566))
    assert fin.minorities == 0


def test_guararapes_two_da_lines_and_lease_receivable_excluded(env):
    repo, uni, _ = env
    fin = Extractor(repo).extract(uni.resolve("GUAR3").cnpj, "Guararapes")
    da = (491.475 + 270.673) + (264.525 + 137.686) - (228.430 + 128.548)
    assert approx(fin.ltm.da, da)
    assert approx(fin.leases, 260.166 + 981.126)   # "arrendamento a receber" não entra
    assert approx(fin.cash, 918.437 + 218.014)
    # 3.11.01/3.11.02 vêm zerados: usa o lucro total (3.11), não zero
    assert approx(fin.ltm.net_income, 1475.168 + 172.958 - 116.560)
    # outras receitas operacionais relevantes viram aviso de possível não recorrente
    assert any("não recorrente" in w for w in fin.warnings)


def test_vivara_unidade_scale_and_versions(env):
    repo, uni, _ = env
    fin = Extractor(repo).extract(uni.resolve("VIVA3").cnpj, "Vivara")
    assert approx(fin.ltm.revenue, 3026.581564 + 1428.643410 - 1100.912502)
    assert approx(fin.leases, 15.241383 + 83.722353 + 608.465095)


def test_share_scale_resolution():
    # Renner: 1.006.845 reportado (milhares), preço ~R$15, PL ~R$10,4 bi
    assert resolve_share_scale(976_323, 15.0, 10_368, None)[0] == 1000
    # Mateus: 2,3 bi reportado (unidades)
    assert resolve_share_scale(2_302_281_840, 7.0, 11_185, None)[0] == 1
    # Com nº de ações do Yahoo, a comparação direta manda
    assert resolve_share_scale(1_338_440, 9.0, 6_346, 1_338_000_000)[0] == 1000


def test_build_comps_end_to_end(env):
    repo, uni, prices = env
    res = build_comps("GUAR3", ["GMAT3", "ASAI3", "VIVA3", "XXXX3"], repo, uni, prices)
    assert list(res.table["Ticker"]) == ["RIAA3", "GMAT3", "ASAI3", "VIVA3"]
    assert "XXXX3" in res.errors and res.renamed == {"RIAA3": "GUAR3"}
    asai = res.table.set_index("Ticker").loc["ASAI3"]
    mcap = 1_338_440 * 1000 * 9.0 / 1e6
    assert approx(asai["Valor de Mercado"], mcap)
    ev = mcap + (2176 + 14106 - 4473) + (511 + 10200)
    assert approx(asai["EV"], ev)
    assert approx(asai["EV/EBITDA"], ev / ((3623 + 2704 - 1934) + (1755 + 927 - 866)))
    assert not res.stats.empty and "Mediana" in res.stats.index
    val = implied_valuation(res, "EV/EBITDA")
    assert val and val["P25"]["preço_por_ação"] <= val["P75"]["preço_por_ação"]


def test_valuation_with_mocked_ai(env, tmp_path, monkeypatch):
    import json

    import comps.ai as ai
    from comps.excel_model import export_model
    from comps.valuation import build_valuation

    repo, uni, prices = env
    res = build_comps("GMAT3", ["RIAA3", "ASAI3", "VIVA3"], repo, uni, prices)
    resp = {"cenarios": {
        "pessimista": {"crescimento": [3, 3, 3, 3, 3], "margem": [0.04] * 5, "capex_pct": 0.01, "capital_giro_pct": 0.12,
                       "teses": [2], "justificativa": {"margem": "competição"}},
        "base": {"crescimento": [0.06] * 5, "margem": [0.05] * 5, "capex_pct": 0.01, "capital_giro_pct": 0.12,
                 "teses": [1, 2], "justificativa": {}},
        "otimista": {"crescimento": [0.09] * 5, "margem": [0.06, 0.06, 0.06, 0.40, 0.06], "capex_pct": 0.01,
                     "capital_giro_pct": 0.12, "teses": [1, 9], "justificativa": {}}}}
    monkeypatch.setattr(ai, "ai_available", lambda: True)
    monkeypatch.setattr(ai, "_ask", lambda s, u, max_tokens=0: json.dumps(resp))
    v = build_valuation(res, ["Expansão no Nordeste", "Competição no atacarejo"], fetch_beta=False)
    assert v.assumptions_source.startswith("IA")
    assert v.scenarios["pessimista"].growth[0] == 0.03            # "3" vira 3%
    assert v.scenarios["otimista"].theses_used == [1]             # tese 9 não existe
    assert any("margem do ano 4" in w for w in v.warnings)        # 40% de margem é travado
    assert v.dcf["pessimista"].per_share < v.dcf["base"].per_share < v.dcf["otimista"].per_share
    assert export_model(v, tmp_path / "m.xlsx", comps=res).exists()
    assert v.recommendation in ("COMPRA", "NEUTRO", "VENDA")


def test_rule_peers_rank_by_activity(env):
    _, uni, _ = env
    peers = uni.rule_peers(uni.resolve("GMAT3"))
    assert peers[0][0].main_ticker == "ASAI3"        # "atacarejo" em comum vem primeiro
    assert {c.main_ticker for c, _ in peers} == {"ASAI3", "RIAA3", "VIVA3"}


def test_invalid_fca_codes(env):
    _, uni, _ = env
    # Marisa: "022055" no FCA não é ticker; a correção conhecida leva ao AMAR3
    assert "022055" not in uni.by_ticker
    marisa = uni.resolve("AMAR3")
    assert marisa.main_ticker == "AMAR3" and "022055" in uni.ticker_notes[marisa.cnpj]
    assert uni.resolve("022055").main_ticker == "AMAR3"
    # sem correção: fica fora da lista e o erro explica o motivo
    assert all(c.name != "SEM TICKER S.A." for c in uni.listed(active_only=False))
    with pytest.raises(KeyError, match="não é um ticker da B3"):
        uni.resolve("N/A")


def test_target_without_quote_is_reported(env, tmp_path):
    repo, uni, _ = env
    d = tmp_path / "p"
    d.mkdir()
    (d / "precos_manuais.csv").write_text("ticker;preco;data\nASAI3;9,00;2026-10-28\n")   # sem preço para o alvo
    res = build_comps("GMAT3", ["ASAI3"], repo, uni, PriceProvider(d, use_yahoo=False))
    assert not res.target_ok and "GMAT3" in res.errors
