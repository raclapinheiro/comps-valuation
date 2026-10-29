"""Extração dos números de uma empresa a partir das demonstrações da CVM.

Regras principais (todas documentadas na aba "Notas" do Excel):

* Base: consolidado quando a empresa publica consolidado; senão, individual
  (empresas sem controladas, como o Assaí, só entregam o individual).
* LTM (últimos 12 meses) = último ano fechado (DFP) + acumulado do ano no último ITR
  - acumulado do mesmo período do ano anterior (coluna "PENÚLTIMO" do próprio ITR).
* EBITDA = EBIT (3.05, resultado antes do resultado financeiro e dos tributos)
  + Depreciação e Amortização (linhas de D&A no DFC; fallback: DVA 7.04.01).
* Dívida bruta = 2.01.04 + 2.02.01 (empréstimos, financiamentos e debêntures).
  Arrendamentos (IFRS 16) são separados, estejam eles dentro ou fora dessas contas.
* Caixa = 1.01.01 + 1.01.02 (caixa e aplicações financeiras de curto prazo).
* Minoritários = 2.03.09.
* Todo número carrega a trilha de auditoria: documento, data, conta CVM e valor original.

Valores internos sempre em R$ milhões.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .cvm import CVMDataUnavailable, CVMRepository, years_to_try

# D&A no DFC: linhas de ajuste do lucro (6.01.01.xx) que falam de depreciação/amortização/exaustão…
DA_RX = re.compile(r"deprecia|amortiza|exaust", re.I)
# …exceto amortização de custos de captação, juros, empréstimos e o passivo de arrendamento
DA_EXCLUDE_RX = re.compile(r"custos? d[eo]s? (?:transa|capta|emiss)|juros|empr[ée]stimo|deb[êe]nture|capta[çc]|passivo|financiamento|des[áa]gio", re.I)
# Passivo de arrendamento (IFRS 16) no balanço
LEASE_RX = re.compile(r"arrendament|passivos? de loca|obriga[çc][õo]es (?:com|de|por) loca|loca[çc][õo]es a pagar", re.I)
LEASE_EXCLUDE_RX = re.compile(r"receber", re.I)
# Pagamentos de arrendamento no DFC (atividades de financiamento)
LEASE_PAY_EXCLUDE_RX = re.compile(r"adi[çc][ãa]o|novos contratos|remensura|capta", re.I)
# Capex no DFC (6.02.xx): aquisição/adição de imobilizado ou intangível, sem vendas e sem M&A
CAPEX_RX = re.compile(r"imobilizad|intang[íi]v|ativos? fixos?", re.I)
CAPEX_EXCLUDE_RX = re.compile(r"venda|receb|aliena|combina|controlad|investid|baixa", re.I)

MULT = {"MIL": 1_000.0, "UNIDADE": 1.0}


@dataclass
class AuditLine:
    metric: str
    value_mm: float
    document: str           # ex.: "ITR 30/06/2026 (consolidado)"
    accounts: str           # ex.: "3.05 Resultado Antes do Resultado Financeiro…"
    formula: str = ""       # ex.: "FY25 + 6M26 - 6M25"
    link: str = ""


@dataclass
class Period:
    """Valores de um período de fluxo (DRE/DFC/DVA)."""
    revenue: float = 0.0
    gross_profit: float = 0.0
    ebit: float = 0.0
    da: float = 0.0
    da_dva: float = 0.0
    net_income: float = 0.0          # atribuído aos controladores
    net_income_total: float = 0.0
    lease_payments: float = 0.0      # principal + juros pagos de arrendamento (positivo)
    other_operating: float = 0.0     # outras receitas (+) e despesas (-) operacionais: 3.04.04 + 3.04.05
    capex: float = 0.0               # aquisição de imobilizado + intangível no DFC (positivo)
    ebt: float = 0.0                 # 3.07 lucro antes dos impostos
    taxes: float = 0.0               # 3.08 IR/CS (negativo quando é despesa)

    @property
    def ebitda(self) -> float:
        return self.ebit + self.da

    def __add__(self, o: "Period") -> "Period":
        return Period(**{k: getattr(self, k) + getattr(o, k) for k in self.__dataclass_fields__})

    def __sub__(self, o: "Period") -> "Period":
        return Period(**{k: getattr(self, k) - getattr(o, k) for k in self.__dataclass_fields__})


@dataclass
class CompanyFinancials:
    cnpj: str
    name: str
    basis: str                       # 'consolidado' | 'individual'
    fy_label: str                    # ex.: '2025'
    ltm_label: str                   # ex.: 'LTM 2T26'
    ltm_end: str                     # data de referência do balanço (AAAA-MM-DD)
    fy: Period
    fy_prev: Period
    ltm: Period
    cash: float = 0.0
    debt_gross: float = 0.0
    leases: float = 0.0
    leases_in_debt: float = 0.0
    minorities: float = 0.0
    equity_total: float = 0.0
    shares_on: float = 0.0           # quantidade como reportada à CVM (escala resolvida em market.py)
    shares_pn: float = 0.0
    receivables: float = 0.0         # 1.01.03 contas a receber
    inventory: float = 0.0           # 1.01.04 estoques
    payables: float = 0.0            # 2.01.02 fornecedores
    audit: list[AuditLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def debt_ex_leases(self) -> float:
        return self.debt_gross - self.leases_in_debt

    @property
    def net_debt(self) -> float:
        """Dívida líquida sem arrendamentos (conceito usado em covenants)."""
        return self.debt_ex_leases - self.cash

    @property
    def equity_controller(self) -> float:
        return self.equity_total - self.minorities

    @property
    def working_capital(self) -> float:
        """Capital de giro operacional = contas a receber + estoques - fornecedores."""
        return self.receivables + self.inventory - self.payables


# ---------------------------------------------------------------------- helpers
def _br(v: float) -> str:
    """1234.5 -> '1.235' (milhar com ponto, padrão brasileiro)."""
    return f"{v:,.0f}".replace(",", ".")


def _fmt_date(d: str) -> str:
    y, m, dd = d.split("-")
    return f"{dd}/{m}/{y}"


def _quarter_label(d: str) -> str:
    y, m, _ = d.split("-")
    return f"{int(m) // 3}T{y[2:]}"


def _company_rows(df: pd.DataFrame, cnpj: str, dt_refer: str) -> pd.DataFrame:
    rows = df[(df["CNPJ_CIA"] == cnpj) & (df["DT_REFER"] == dt_refer)]
    if rows.empty:
        return rows
    # Reapresentações: fica só a versão mais recente do documento
    return rows[rows["VERSAO"] == rows["VERSAO"].max()]


def _scaled(rows: pd.DataFrame) -> pd.Series:
    """VL_CONTA em R$ milhões, respeitando a escala (MIL ou UNIDADE) de cada linha."""
    mult = np.array([MULT.get(str(e).strip().upper(), 1_000.0) for e in rows["ESCALA_MOEDA"]], dtype=float)
    vals = rows["VL_CONTA"].to_numpy(dtype=float)
    return pd.Series(vals * mult / 1e6, index=rows.index, dtype="float64")


def _mask(df: pd.DataFrame, *conds) -> pd.DataFrame:
    """Aplica condições como arrays numpy de bool (evita surpresas de tipo em frames vazios)."""
    if df.empty:
        return df
    m = np.ones(len(df), dtype=bool)
    for c in conds:
        m &= np.asarray(c, dtype=bool)
    return df[m]


def _is_leaf(code: str, all_codes: set[str]) -> bool:
    prefix = code + "."
    return not any(c.startswith(prefix) for c in all_codes)


class Extractor:
    def __init__(self, repo: CVMRepository):
        self.repo = repo

    # ---------------------------------------------------------------- documentos
    def _latest_doc(self, doc: str, cnpj: str, years: list[int], after: str = "") -> tuple[int, str] | None:
        """(ano do arquivo, DT_REFER) do documento mais recente da empresa."""
        for year in years:
            try:
                idx = self.repo.doc_index(doc, year)
            except CVMDataUnavailable:
                continue
            dates = idx.loc[idx["CNPJ_CIA"] == cnpj, "DT_REFER"]
            dates = dates[dates > after]
            if not dates.empty:
                return year, dates.max()
        return None

    def _doc_link(self, doc: str, year: int, cnpj: str, dt_refer: str) -> str:
        try:
            idx = self.repo.doc_index(doc, year)
        except CVMDataUnavailable:
            return ""
        r = idx[(idx["CNPJ_CIA"] == cnpj) & (idx["DT_REFER"] == dt_refer)]
        if r.empty or "LINK_DOC" not in r:
            return ""
        return r.sort_values("VERSAO").iloc[-1]["LINK_DOC"]

    def _basis(self, doc: str, year: int, cnpj: str, dt_refer: str) -> bool:
        """True se a empresa tem demonstração consolidada naquele documento."""
        try:
            con = self.repo.statement(doc, year, "DRE", consolidated=True)
        except CVMDataUnavailable:
            return False
        return not _company_rows(con, cnpj, dt_refer).empty

    # ---------------------------------------------------------------- fluxos
    def _period(self, doc: str, year: int, cnpj: str, dt_refer: str, consolidated: bool,
                ordem: str, label: str, audit: list[AuditLine], link: str) -> Period:
        """Lê um período acumulado no ano (DT_INI_EXERC em 1º de janeiro).

        ordem: 'ÚLTIMO' (período do documento) ou 'PENÚLTIMO' (mesmo período do ano anterior).
        """
        p = Period()
        basis_txt = "consolidado" if consolidated else "individual"
        docname = f"{doc.upper()} {_fmt_date(dt_refer)} ({basis_txt}, {ordem.lower()})"

        def rows_for(stmt: str) -> pd.DataFrame:
            try:
                df = self.repo.statement(doc, year, stmt, consolidated)
            except CVMDataUnavailable:
                return pd.DataFrame()
            r = _company_rows(df, cnpj, dt_refer)
            if r.empty:
                return r
            r = r[r["ORDEM_EXERC"].str.upper().str.startswith(ordem[:3].upper())]
            # Só o acumulado do ano (no ITR há também as colunas do trimestre isolado)
            r = r[r["DT_INI_EXERC"].str.endswith("-01-01")]
            return r.assign(VALOR=_scaled(r))

        def val(r: pd.DataFrame, code: str) -> tuple[float, str]:
            hit = r[r["CD_CONTA"] == code]
            if hit.empty:
                return 0.0, ""
            return float(hit["VALOR"].iloc[0]), f"{code} {hit['DS_CONTA'].iloc[0]}"

        dre = rows_for("DRE")
        p.revenue, a_rev = val(dre, "3.01")
        p.gross_profit, a_gp = val(dre, "3.03")
        p.ebit, a_ebit = val(dre, "3.05")
        p.net_income_total, a_ni = val(dre, "3.11")
        ni_ctrl, a_nic = val(dre, "3.11.01")
        ni_min, _ = val(dre, "3.11.02")
        # Algumas empresas preenchem 3.11.01 e 3.11.02 com zero (ex.: Guararapes). Só usamos a
        # divisão controladores/minoritários quando ela fecha com o lucro total.
        split_ok = a_nic and abs(ni_ctrl + ni_min - p.net_income_total) <= max(0.5, 0.01 * abs(p.net_income_total))
        p.net_income = ni_ctrl if split_ok else p.net_income_total
        if not split_ok:
            a_nic = ""
        other_in, _ = val(dre, "3.04.04")
        other_out, _ = val(dre, "3.04.05")
        p.other_operating = other_in + other_out
        p.ebt, _ = val(dre, "3.07")
        p.taxes, _ = val(dre, "3.08")
        for metric, v, acc in (("Receita líquida", p.revenue, a_rev), ("Lucro bruto", p.gross_profit, a_gp),
                               ("EBIT", p.ebit, a_ebit),
                               ("Lucro líquido (controladores)", p.net_income, a_nic or a_ni)):
            audit.append(AuditLine(f"{metric} [{label}]", v, docname, acc, link=link))

        # D&A: DFC (linhas folha de 6.01.01.xx) com DVA 7.04.01 como alternativa/checagem
        dfc = rows_for("DFC_MI")
        da_rows = pd.DataFrame()
        if not dfc.empty:
            codes = set(dfc["CD_CONTA"])
            code_s, desc_s = list(dfc["CD_CONTA"]), list(dfc["DS_CONTA"])
            leaf = [_is_leaf(c, codes) for c in code_s]
            da_rows = _mask(dfc,
                            [c.startswith("6.01.01.") for c in code_s],
                            [bool(DA_RX.search(d)) and not DA_EXCLUDE_RX.search(d) for d in desc_s],
                            leaf)
            lease_rows = _mask(dfc,
                               [c.startswith("6.03") for c in code_s],
                               [bool(LEASE_RX.search(d)) and not LEASE_PAY_EXCLUDE_RX.search(d) for d in desc_s],
                               dfc["VALOR"].to_numpy(dtype=float) < 0,
                               leaf)
            p.lease_payments = float(-lease_rows["VALOR"].sum())
            capex_rows = _mask(dfc,
                               [c.startswith("6.02.") for c in code_s],
                               [bool(CAPEX_RX.search(d)) and not CAPEX_EXCLUDE_RX.search(d) for d in desc_s],
                               dfc["VALOR"].to_numpy(dtype=float) < 0,
                               leaf)
            p.capex = float(-capex_rows["VALOR"].sum())
            if not capex_rows.empty:
                audit.append(AuditLine(f"Capex [{label}]", p.capex, docname,
                                       "; ".join(capex_rows["CD_CONTA"] + " " + capex_rows["DS_CONTA"]), link=link))
            if not lease_rows.empty:
                audit.append(AuditLine(f"Pagamentos de arrendamento [{label}]", p.lease_payments, docname,
                                       "; ".join(lease_rows["CD_CONTA"] + " " + lease_rows["DS_CONTA"]), link=link))
        dva = rows_for("DVA")
        p.da_dva = abs(val(dva, "7.04.01")[0]) if not dva.empty else 0.0
        da_dfc = float(da_rows["VALOR"].abs().sum()) if not da_rows.empty else 0.0

        if da_dfc > 0:
            p.da = da_dfc
            acc = "; ".join(da_rows["CD_CONTA"] + " " + da_rows["DS_CONTA"])
            audit.append(AuditLine(f"D&A [{label}]", p.da, docname, f"DFC: {acc}", link=link))
        else:
            p.da = p.da_dva
            audit.append(AuditLine(f"D&A [{label}]", p.da, docname, "DVA 7.04.01 Depreciação, Amortização e Exaustão",
                                   formula="DFC sem linha de D&A identificável", link=link))
        return p

    # ---------------------------------------------------------------- balanço
    def _balance(self, doc: str, year: int, cnpj: str, dt_refer: str, consolidated: bool,
                 fin: CompanyFinancials, link: str) -> None:
        basis_txt = "consolidado" if consolidated else "individual"
        docname = f"{doc.upper()} {_fmt_date(dt_refer)} ({basis_txt})"

        def rows_for(stmt: str) -> pd.DataFrame:
            df = self.repo.statement(doc, year, stmt, consolidated)
            r = _company_rows(df, cnpj, dt_refer)
            r = r[r["ORDEM_EXERC"].str.upper().str.startswith("ÚLT") | r["ORDEM_EXERC"].str.upper().str.startswith("ULT")]
            return r.assign(VALOR=_scaled(r))

        bpa, bpp = rows_for("BPA"), rows_for("BPP")

        def val(r: pd.DataFrame, code: str) -> float:
            hit = r[r["CD_CONTA"] == code]
            return float(hit["VALOR"].iloc[0]) if not hit.empty else 0.0

        cash, invest = val(bpa, "1.01.01"), val(bpa, "1.01.02")
        fin.cash = cash + invest
        fin.audit.append(AuditLine("Caixa e aplicações", fin.cash, docname,
                                   "1.01.01 Caixa e Equivalentes + 1.01.02 Aplicações Financeiras",
                                   formula=f"{cash:,.1f} + {invest:,.1f}", link=link))

        st, lt = val(bpp, "2.01.04"), val(bpp, "2.02.01")
        fin.debt_gross = st + lt
        fin.audit.append(AuditLine("Dívida bruta (com arrend. contidos)", fin.debt_gross, docname,
                                   "2.01.04 + 2.02.01 Empréstimos e Financiamentos (inclui debêntures)",
                                   formula=f"{st:,.1f} + {lt:,.1f}", link=link))

        codes = set(bpp["CD_CONTA"])
        code_s, desc_s = list(bpp["CD_CONTA"]), list(bpp["DS_CONTA"])
        leases = _mask(bpp,
                       [bool(re.match(r"2\.0[12]\.", c)) for c in code_s],
                       [bool(LEASE_RX.search(d)) and not LEASE_EXCLUDE_RX.search(d) for d in desc_s],
                       [_is_leaf(c, codes) for c in code_s])
        in_debt = _mask(leases, [bool(re.match(r"2\.01\.04|2\.02\.01", c)) for c in leases["CD_CONTA"]])
        fin.leases = float(leases["VALOR"].sum())
        fin.leases_in_debt = float(in_debt["VALOR"].sum())
        if not leases.empty:
            fin.audit.append(AuditLine("Passivo de arrendamento (IFRS 16)", fin.leases, docname,
                                       "; ".join(leases["CD_CONTA"] + " " + leases["DS_CONTA"]), link=link))
        if fin.leases_in_debt:
            fin.audit.append(AuditLine("Arrendamento dentro de 2.01.04/2.02.01", fin.leases_in_debt, docname,
                                       "; ".join(in_debt["CD_CONTA"] + " " + in_debt["DS_CONTA"]),
                                       formula="subtraído da dívida bruta para evitar dupla contagem", link=link))

        fin.receivables, fin.inventory = val(bpa, "1.01.03"), val(bpa, "1.01.04")
        fin.payables = val(bpp, "2.01.02")
        fin.audit.append(AuditLine("Capital de giro operacional", fin.working_capital, docname,
                                   "1.01.03 Contas a Receber + 1.01.04 Estoques - 2.01.02 Fornecedores",
                                   formula=f"{fin.receivables:,.1f} + {fin.inventory:,.1f} - {fin.payables:,.1f}", link=link))
        fin.minorities = val(bpp, "2.03.09") if consolidated else 0.0
        fin.equity_total = val(bpp, "2.03")
        fin.audit.append(AuditLine("Participação de não controladores", fin.minorities, docname,
                                   "2.03.09 Participação dos Acionistas Não Controladores", link=link))
        fin.audit.append(AuditLine("Patrimônio líquido total", fin.equity_total, docname, "2.03", link=link))

    def _shares(self, doc: str, year: int, cnpj: str, dt_refer: str, fin: CompanyFinancials) -> None:
        cap = self.repo.capital(doc, year)
        r = cap[(cap["CNPJ_CIA"] == cnpj) & (cap["DT_REFER"] == dt_refer)]
        if r.empty:  # cai para o documento mais recente que tiver composição do capital
            r = cap[cap["CNPJ_CIA"] == cnpj]
        if r.empty:
            fin.warnings.append("Composição do capital não encontrada na CVM")
            return
        r = r.sort_values(["DT_REFER", "VERSAO"]).iloc[-1]
        fin.shares_on = r["QT_ACAO_ORDIN_CAP_INTEGR"] - r["QT_ACAO_ORDIN_TESOURO"]
        fin.shares_pn = r["QT_ACAO_PREF_CAP_INTEGR"] - r["QT_ACAO_PREF_TESOURO"]
        fin.audit.append(AuditLine("Ações ex-tesouraria (quantidade reportada)", fin.shares_on + fin.shares_pn,
                                   f"{doc.upper()} {_fmt_date(r['DT_REFER'])} - composição do capital",
                                   "QT_ACAO_TOTAL_CAP_INTEGR - QT_ACAO_TOTAL_TESOURO",
                                   formula=f"ON {fin.shares_on:,.0f} / PN {fin.shares_pn:,.0f} (escala resolvida com o preço)"))

    # ---------------------------------------------------------------- orquestração
    def extract(self, cnpj: str, name: str = "") -> CompanyFinancials:
        years = years_to_try()
        dfp = self._latest_doc("dfp", cnpj, years)
        if dfp is None:
            raise CVMDataUnavailable(f"Nenhuma DFP encontrada para {name or cnpj}")
        dfp_year, fy_end = dfp
        itr = self._latest_doc("itr", cnpj, [y for y in years if y > dfp_year], after=fy_end)

        audit: list[AuditLine] = []
        dfp_link = self._doc_link("dfp", dfp_year, cnpj, fy_end)
        consolidated = self._basis("dfp", dfp_year, cnpj, fy_end)
        fy = self._period("dfp", dfp_year, cnpj, fy_end, consolidated, "ÚLTIMO", f"FY{fy_end[2:4]}", audit, dfp_link)
        fy_prev = self._period("dfp", dfp_year, cnpj, fy_end, consolidated, "PENÚLTIMO",
                               f"FY{int(fy_end[2:4]) - 1:02d}", audit, dfp_link)

        if itr:
            itr_year, itr_end = itr
            itr_link = self._doc_link("itr", itr_year, cnpj, itr_end)
            itr_con = self._basis("itr", itr_year, cnpj, itr_end)
            q = _quarter_label(itr_end)
            ytd = self._period("itr", itr_year, cnpj, itr_end, itr_con, "ÚLTIMO", f"YTD {q}", audit, itr_link)
            ytd_prev = self._period("itr", itr_year, cnpj, itr_end, itr_con, "PENÚLTIMO",
                                    f"YTD {q[:2]}{int(q[2:]) - 1:02d}", audit, itr_link)
            ltm = fy + ytd - ytd_prev
            ltm_label, bal_doc, bal_year, bal_end, bal_link, bal_con = f"LTM {q}", "itr", itr_year, itr_end, itr_link, itr_con
            formula = f"FY{fy_end[2:4]} + YTD {q} - YTD {q[:2]}{int(q[2:]) - 1:02d}"
        else:
            ltm, ltm_label = fy, f"FY{fy_end[2:4]}"
            bal_doc, bal_year, bal_end, bal_link, bal_con = "dfp", dfp_year, fy_end, dfp_link, consolidated
            formula = "último ano fechado (sem ITR posterior)"

        fin = CompanyFinancials(
            cnpj=cnpj, name=name, basis="consolidado" if bal_con else "individual",
            fy_label=fy_end[:4], ltm_label=ltm_label, ltm_end=bal_end,
            fy=fy, fy_prev=fy_prev, ltm=ltm, audit=audit,
        )
        if itr and itr_con != consolidated:
            fin.warnings.append("Base do ITR (consolidado/individual) difere da DFP; LTM combina bases diferentes")

        for metric, v in (("Receita líquida", ltm.revenue), ("EBIT", ltm.ebit), ("D&A", ltm.da),
                          ("Outras receitas/despesas operacionais (3.04.04 + 3.04.05)", ltm.other_operating),
                          ("EBITDA", ltm.ebitda), ("Lucro líquido (controladores)", ltm.net_income),
                          ("Pagamentos de arrendamento", ltm.lease_payments)):
            fin.audit.append(AuditLine(f"{metric} [{ltm_label}]", v, "Cálculo", "", formula=formula))

        self._balance(bal_doc, bal_year, cnpj, bal_end, bal_con, fin, bal_link)
        self._shares(bal_doc, bal_year, cnpj, bal_end, fin)

        # ------------------------------------------------ checagens de sanidade
        if ltm.revenue <= 0:
            fin.warnings.append("Receita LTM não encontrada (empresa financeira ou layout diferente?)")
        if ltm.da == 0:
            fin.warnings.append("D&A não encontrada: EBITDA = EBIT")
        elif ltm.da_dva > 0 and abs(ltm.da - ltm.da_dva) / ltm.da_dva > 0.15:
            # Diferença explicada: o DFC tem depreciação do direito de uso (IFRS 16) e a DVA não
            rou = any(a.metric.startswith("D&A") and re.search(r"direito de uso|arrendament", a.accounts, re.I)
                      for a in fin.audit)
            if not (rou and ltm.da > ltm.da_dva):
                fin.warnings.append(f"D&A do DFC ({_br(ltm.da)}) difere mais de 15% da DVA ({_br(ltm.da_dva)})")
        if ltm.ebit and abs(ltm.other_operating) > max(0.25 * abs(ltm.ebit), 0.02 * ltm.revenue):
            fin.warnings.append(
                f"Outras receitas/despesas operacionais de R$ {_br(ltm.other_operating)} mi no LTM "
                f"({ltm.other_operating / ltm.ebit:.0%} do EBIT): possível item não recorrente, conferir no release")
        if fin.leases == 0 and ltm.lease_payments > 0:
            fin.warnings.append("Há pagamentos de arrendamento no DFC, mas o passivo não foi identificado no balanço")
        return fin
