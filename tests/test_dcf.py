"""Testes do DCF: conta feita à mão, travas das premissas e ordem dos cenários."""
from __future__ import annotations

import math

from comps.dcf import Base, Scenario, Wacc, check_ordering, run_dcf, validate


def _base():
    return Base(label="LTM", revenue=100.0, ebitda_ex16=20.0, capex=5.0, da=6.0, nwc=10.0,
                growth_fy=0.10, margin_fy_prev=0.19, tax_effective=0.30)


def _scen(**kw):
    d = dict(name="base", growth=[0.10] * 5, margin=[0.20] * 5, capex_pct=0.05, da_pct=0.05, nwc_pct=0.10,
             terminal_growth=0.03)
    d.update(kw)
    return Scenario(**d)


def test_dcf_matches_hand_calculation():
    wacc = Wacc(rf=0.10, beta=1.0, erp=0.0, kd_pre=0.10, tax=0.34, equity_value=1000, net_debt=-50)
    assert math.isclose(wacc.value, 0.10)             # caixa líquido: peso da dívida = 0, WACC = Ke
    res = run_dcf(_base(), _scen(), wacc, minorities=5.0, shares=10e6, price=10.0)
    # Conta à mão, ano a ano
    rev, nwc_prev, pv = 100.0, 10.0, 0.0
    for t in range(1, 6):
        rev *= 1.10
        ebitda, da = 0.20 * rev, 0.05 * rev
        fcff = ebitda - 0.34 * (ebitda - da) - 0.05 * rev - (0.10 * rev - nwc_prev)
        nwc_prev = 0.10 * rev
        pv += fcff / 1.10 ** t
    tv = fcff * 1.03 / (0.10 - 0.03)
    ev = pv + tv / 1.10 ** 5
    assert math.isclose(res.ev, ev, rel_tol=1e-9)
    assert math.isclose(res.equity, ev + 50 - 5.0, rel_tol=1e-9)    # caixa líquido soma, minoritários subtraem
    assert math.isclose(res.per_share, (ev + 45) * 1e6 / 10e6, rel_tol=1e-9)


def test_validate_clamps_and_reports():
    s, w = validate(_scen(growth=[0.9, 0.1, 0.1, 0.1, 0.1], margin=[0.20, 0.20, 0.60, 0.20, 0.20]), _base())
    assert s.growth[0] == 0.50 and math.isclose(s.margin[2], 0.35)   # margem: histórica (20%) + 15 p.p.
    assert len(w) == 2


def test_ordering_warning():
    scen = {"pessimista": _scen(name="pessimista", growth=[0.12] * 5), "base": _scen(), "otimista": _scen(name="otimista")}
    assert any("crescimento" in w for w in check_ordering(scen))


def test_wacc_not_above_growth_flags():
    wacc = Wacc(rf=0.02, beta=1.0, erp=0.0, kd_pre=0.02, tax=0.34, equity_value=1000, net_debt=0)
    res = run_dcf(_base(), _scen(terminal_growth=0.05), wacc, 0, 10e6, 10.0)
    assert math.isnan(res.ev) and any("valor terminal" in w for w in res.warnings)
