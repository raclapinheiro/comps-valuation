"""Interface web: comps e valuation por teses a partir de dados da CVM.

Rodar:  python -m streamlit run app.py
"""
from __future__ import annotations

import os
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from comps import ui
from comps.ai import ai_available, describe_business, suggest_peers, suggest_theses
from comps.config import DEMO_PEERS, DEMO_TARGET, OUTPUT_DIR
from comps.cvm import CVMRepository
from comps.dcf import MARKET_DEFAULTS, YEARS, Scenario
from comps.engine import build_comps, implied_valuation
from comps.excel import export_excel
from comps.excel_model import export_model
from comps.market import PriceProvider
from comps.onepager import export_onepager
from comps.universe import Universe
from comps.valuation import BUY_UPSIDE, SELL_UPSIDE, _hist_text, build_valuation, history_table, summary
from comps.ui import br, mm, pc, xx

st.set_page_config(page_title="Comps & Valuation", page_icon="📈", layout="wide", initial_sidebar_state="collapsed")
st.markdown(ui.CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------- nuvem: segredos e senha
def _secret(name: str) -> str:
    """Na nuvem (Streamlit Community Cloud) as chaves ficam em Settings > Secrets; no PC, no arquivo .env."""
    try:
        return str(st.secrets.get(name, "") or "")
    except Exception:  # noqa: BLE001 - sem secrets.toml (uso local)
        return ""


for _k in ("ANTHROPIC_API_KEY",):
    if _secret(_k) and not os.environ.get(_k):
        os.environ[_k] = _secret(_k)

_pw = _secret("APP_PASSWORD")
if _pw and not st.session_state.get("auth_ok"):
    st.markdown(ui.brand(), unsafe_allow_html=True)
    st.markdown("<div class='ph' style='margin-top:28px'>Acesso restrito</div>"
                "<p class='psub'>Digite a senha para abrir o app.</p>", unsafe_allow_html=True)
    _c, _ = st.columns([1, 2])
    _typed = _c.text_input("Senha", type="password", label_visibility="collapsed", placeholder="Senha")
    if _c.button("Entrar", type="primary"):
        if _typed == _pw:
            st.session_state.auth_ok = True
            st.rerun()
        _c.error("Senha incorreta.")
    st.stop()

PAGES = ["Comparar empresas", "Valuation por teses", "Auditoria", "Arquivos"]


# ---------------------------------------------------------------------- dados
@st.cache_resource(show_spinner="Carregando o cadastro de empresas da CVM (na primeira vez leva cerca de 1 minuto)…")
def load_universe() -> tuple[CVMRepository, Universe]:
    repo = CVMRepository()
    return repo, Universe(repo)


repo, universe = load_universe()
companies = {c.main_ticker: c for c in universe.listed() if c.main_ticker}
options = sorted(companies)


def name_of(t: str) -> str:
    c = companies.get(t)
    return ui.short_name(c.name) if c else t


def label(t: str) -> str:
    return f"{t}  {name_of(t)}" if t in companies else t


ss = st.session_state
if "target" not in ss:
    ss.target = DEMO_TARGET if DEMO_TARGET in companies else options[0]
    ss.peers = [p for p in DEMO_PEERS if p in companies]
    ss.peer_reasons = {}
    ss.peers_for = ss.target
    ss.page = PAGES[0]
# O multiselect pode não estar na tela (outra página); "peers" guarda a seleção de verdade
if "peers_ms" not in ss:
    ss.peers_ms = list(ss.peers)


def _on_target_change():
    ss.peers_for = None                 # pede para recalcular os peers do novo alvo
    for k in ("val", "files", "val_files", "theses_text"):
        ss.pop(k, None)


def _on_peers_change():
    ss.peers = list(ss.peers_ms)


def _refresh_peers(use_ai: bool):
    comp = companies[ss.target]
    if use_ai and ai_available():
        sugg = suggest_peers(comp, universe)
        peers = [p.ticker for p in sugg if p.ticker in companies and p.ticker != ss.target]
        ss.peer_reasons = {p.ticker: p.reason for p in sugg}
    else:
        rule = universe.rule_peers(comp, 8)
        peers = [c.main_ticker for c, _ in rule if c.main_ticker in companies]
        ss.peer_reasons = {c.main_ticker: why for c, why in rule}
    ss.peers = peers
    ss.peers_ms = list(peers)
    ss.peers_for = ss.target


# ---------------------------------------------------------------------- barra superior
c_brand, c_search, c_go, c_meta = st.columns([1.35, 3.6, 1.05, 1.45], vertical_alignment="center", gap="medium")
c_brand.markdown(ui.brand(), unsafe_allow_html=True)
c_search.selectbox("Buscar empresa", options, key="target", format_func=label, on_change=_on_target_change,
                   label_visibility="collapsed", placeholder="Buscar ticker ou empresa",
                   help="Digite o ticker ou parte do nome")
if ss.get("peers_for") != ss.target:
    with st.spinner("Escolhendo peers para a nova empresa…"):
        _refresh_peers(use_ai=True)
go = c_go.button("Gerar análise", type="primary", use_container_width=True, disabled=not ss.peers)
c_meta.markdown("<div class='topmeta'>Dados da CVM e do Yahoo Finance<br>"
                f"{'IA ligada' if ai_available() else 'IA desligada (sem chave)'}</div>", unsafe_allow_html=True)
st.markdown("<div class='topline'></div>", unsafe_allow_html=True)

if go:
    with st.spinner("Buscando demonstrações na CVM e cotações…"):
        ss.res = build_comps(ss.target, ss.peers, repo, universe, PriceProvider())
        ss.res_sel = (ss.target, tuple(ss.peers))
    for k in ("val", "files", "val_files"):
        ss.pop(k, None)
    ss.page = PAGES[0]

res = ss.get("res")
res_ok = res is not None and res.target_ok
stale = res is not None and ss.get("res_sel") != (ss.target, tuple(ss.peers))

nav, main, rail = st.columns([0.9, 4.2, 1.5], gap="large")
with nav:
    st.radio("Navegação", PAGES, key="page", label_visibility="collapsed")
    st.markdown("<div class='navnote'>Exercício acadêmico com dados públicos. Não é recomendação de investimento.</div>",
                unsafe_allow_html=True)


def quote_items(tickers: list[str]) -> list[dict]:
    out = []
    for t in tickers:
        q = res.quotes.get(t) if res is not None else None
        perf = ui.performance(q.history if q is not None else None)
        out.append({"ticker": t, "name": name_of(t), "role": "Alvo" if t == ss.target else "Peer",
                    "price": q.price if q is not None else None, "change": perf["dia"],
                    "history": q.history if q is not None else None})
    return out


# ---------------------------------------------------------------------- coluna da direita
with rail:
    shown = [ss.target] + [p for p in ss.peers if p != ss.target]
    if res is not None and not stale:
        shown = list(res.table["Ticker"]) if res_ok else shown
    st.markdown(ui.rail_quotes("Na análise", quote_items(shown) if res is not None else
                               [{"ticker": t, "name": name_of(t)} for t in shown],
                               empty="Escolha a empresa na busca."), unsafe_allow_html=True)
    val = ss.get("val")
    if val is not None:
        cls = {"COMPRA": "up", "VENDA": "down"}.get(val.recommendation, "")
        st.markdown(ui.rail_box("Recomendação", f"<div class='recmini {cls}'>{val.recommendation}</div>"
                                + ui.kv("Preço-alvo", f"R$ {br(val.target_price, 2)}")
                                + ui.kv("Upside", f"<span class='{ui.tone(val.upside)}'>{pc(val.upside, sign=True)}</span>")
                                + ui.kv("WACC", pc(val.wacc.value))), unsafe_allow_html=True)
    if res_ok:
        fin = res.financials[res.target]
        q = res.quotes[res.target]
        n_warn = sum(len(v) for v in res.warnings().values())
        st.markdown(ui.rail_box("Fontes", ui.kv("Fundamentos", f"{fin.ltm_label}, {fin.basis}")
                                + ui.kv("Preço", pd.to_datetime(q.as_of).strftime("%d/%m/%Y"))
                                + ui.kv("Avisos de dados", str(n_warn))
                                + "<p class='rmuted' style='margin-top:8px'>Detalhes na página Auditoria.</p>"),
                    unsafe_allow_html=True)


# ---------------------------------------------------------------------- páginas
def page_header(title: str, sub: str = ""):
    st.markdown(f"<div class='ph'>{title}</div>" + (f"<p class='psub'>{sub}</p>" if sub else ""),
                unsafe_allow_html=True)


def need_result() -> bool:
    if res is None:
        st.markdown("<div class='banner'>Nenhuma análise ainda. Escolha a empresa na busca, confira os peers em "
                    "<b>Comparar empresas</b> e clique em <b>Gerar análise</b>.</div>", unsafe_allow_html=True)
        return False
    if not res.target_ok:
        st.error(f"Não foi possível calcular {label(res.target)}: {res.errors.get(res.target, 'motivo não identificado')}.")
        return False
    return True


def page_compare():
    h1, h2 = st.columns([3, 2], vertical_alignment="center")
    with h1:
        page_header("Comparar empresas")
    with h2:
        t1, t2 = st.columns([1.6, 1], vertical_alignment="center")
        highlight = t1.toggle("Destacar melhor e pior", key="hl", help="Verde = melhor do grupo, vermelho = pior. Em múltiplos, menor é melhor.")
        t2.markdown("<span class='pill'>Valores em R$</span>", unsafe_allow_html=True)

    i1, i2 = st.columns([1.15, 4], vertical_alignment="top", gap="medium")
    with i1:
        st.markdown(f"<div class='intro'>Compare {name_of(ss.target)} com as empresas do mesmo setor. "
                    "Os peers mudam sozinhos quando você troca a empresa.</div>", unsafe_allow_html=True)
        with st.popover("Editar peers", use_container_width=True):
            st.multiselect("Peers", options, key="peers_ms", format_func=label, on_change=_on_peers_change,
                           help="Digite para adicionar; clique no x para tirar")
            st.button("Sugerir com IA" if ai_available() else "Sugerir de novo", on_click=_refresh_peers, args=(True,),
                      use_container_width=True)
            if ss.peer_reasons:
                st.markdown("**Por que esses peers**")
                for t in ss.peers:
                    if t in ss.peer_reasons:
                        st.caption(f"{t}: {ss.peer_reasons[t]}")
    with i2:
        sel = [ss.target] + [p for p in ss.peers if p != ss.target]
        st.markdown(ui.company_cards(quote_items(sel)), unsafe_allow_html=True)

    if stale:
        st.markdown("<div class='banner'>A seleção mudou desde a última análise. Clique em <b>Gerar análise</b> "
                    "para atualizar os números.</div>", unsafe_allow_html=True)

    if res is None or stale:
        cols = [{"ticker": t, "target": t == ss.target, "values": {}} for t in sel]
        st.markdown(ui.compare_table(cols, ui.SECTIONS[:3], "Em " + date.today().strftime("%d/%m/%Y"), median={}),
                    unsafe_allow_html=True)
        return
    if not need_result():
        if res.errors:
            st.caption("Empresas que ficaram de fora: " + "; ".join(f"{k} ({v})" for k, v in res.errors.items()))
        return

    cols, med = ui.comps_columns(res)
    as_of = pd.to_datetime(res.quotes[res.target].as_of).strftime("%d/%m/%Y")
    st.markdown(ui.compare_table(cols, ui.SECTIONS, f"Em {as_of}", highlight=highlight, median=med), unsafe_allow_html=True)
    if res.errors:
        st.caption("Ficaram de fora: " + "; ".join(f"{k} ({v})" for k, v in res.errors.items()))
    st.caption("EV inclui dívida líquida, arrendamentos (IFRS 16) e minoritários. Mediana só dos peers. "
               "n.m. quando o denominador é zero ou negativo.")

    left, right = st.columns([1.25, 1], gap="large")
    with left:
        st.markdown("<div class='step'><span class='t'>EV / EBITDA LTM</span></div>", unsafe_allow_html=True)
        bars = res.table[["Ticker", "Papel", "EV/EBITDA"]].dropna()
        ch = alt.Chart(bars).mark_bar(cornerRadiusEnd=4, height=18).encode(
            y=alt.Y("Ticker:N", sort="-x", title=None, axis=alt.Axis(labelColor=ui.TEXT, domain=False, ticks=False)),
            x=alt.X("EV/EBITDA:Q", title=None, axis=alt.Axis(format=".1f")),
            color=alt.Color("Papel:N", scale=alt.Scale(domain=["Alvo", "Peer"], range=[ui.LINK, "#4A5562"]), legend=None),
            tooltip=["Ticker", alt.Tooltip("EV/EBITDA:Q", format=".1f")])
        txt = ch.mark_text(align="left", dx=5, color=ui.MUTED).encode(text=alt.Text("EV/EBITDA:Q", format=".1f"))
        st.altair_chart(ui.dark_chart((ch + txt).properties(height=30 * len(bars) + 20)),
                        use_container_width=True, theme=None)
    with right:
        st.markdown("<div class='step'><span class='t'>Valor implícito pelos peers</span></div>", unsafe_allow_html=True)
        icols = []
        for m in ("EV/EBITDA", "P/L"):
            v = implied_valuation(res, m)
            if v:
                icols.append({"ticker": m, "values": {k: v[k]["preço_por_ação"] for k in ("P25", "Mediana", "P75")}})
        if icols:
            rows = [("Percentil 25", "P25", lambda x: f"R$ {br(x, 2)}", None),
                    ("Mediana", "Mediana", lambda x: f"R$ {br(x, 2)}", None),
                    ("Percentil 75", "P75", lambda x: f"R$ {br(x, 2)}", None)]
            st.markdown(ui.compare_table(icols, [("Preço por ação", rows)], "Percentil dos peers"), unsafe_allow_html=True)
            st.caption(f"Percentis dos peers aplicados ao alvo. Preço atual: R$ {br(res.table.iloc[0]['Preço (R$)'], 2)}.")


def _scenario_editor(name: str, sc: Scenario, key: str) -> Scenario:
    st.markdown(f"**{name.capitalize()}**")
    df = pd.DataFrame([[round(x * 100, 2) for x in sc.growth], [round(x * 100, 2) for x in sc.margin]],
                      index=["Crescimento %", "Margem EBITDA %"], columns=[f"A{i + 1}" for i in range(YEARS)])
    ed = st.data_editor(df, key=f"{key}_grid", use_container_width=True,
                        column_config={c: st.column_config.NumberColumn(format="%.1f") for c in df.columns})
    a, b = st.columns(2)
    capex = a.number_input("Capex / receita %", value=round(sc.capex_pct * 100, 2), step=0.1, key=f"{key}_capex")
    nwc = b.number_input("Capital de giro / receita %", value=round(sc.nwc_pct * 100, 2), step=0.5, key=f"{key}_nwc")
    if sc.rationale:
        with st.expander("Justificativas"):
            for k, txt in sc.rationale.items():
                st.markdown(f"**{k.capitalize()}**: {txt}")
            if sc.theses_used:
                st.caption("Teses usadas: " + ", ".join(f"{i}" for i in sc.theses_used))
    return Scenario(name=name, growth=[float(x) / 100 for x in ed.iloc[0]], margin=[float(x) / 100 for x in ed.iloc[1]],
                    capex_pct=capex / 100, da_pct=sc.da_pct, nwc_pct=nwc / 100, terminal_growth=sc.terminal_growth,
                    rationale=sc.rationale, theses_used=sc.theses_used, source=sc.source)


def _fill_theses():
    with st.spinner("Pensando em teses…"):
        ts = suggest_theses(res.companies[res.target], _hist_text(history_table(res)))
    if ts:
        ss.theses_text = "\n".join(ts)


def page_valuation():
    page_header("Valuation por teses", f"DCF de {name_of(ss.target)} em três cenários. Você escreve as teses, a IA "
                "propõe as premissas e o código faz as contas.")
    if not need_result() or stale:
        if stale:
            st.markdown("<div class='banner'>A seleção mudou. Gere a análise de novo antes do valuation.</div>",
                        unsafe_allow_html=True)
        return
    st.markdown("<div class='step'><span class='n'>1</span><span class='t'>Teses de investimento</span></div>"
                "<p class='hint'>Uma por linha, em palavras, sem números. A IA transforma cada tese em premissas; "
                "você revisa no passo 2.</p>", unsafe_allow_html=True)
    st.text_area("Teses", key="theses_text", height=120, label_visibility="collapsed",
                 placeholder="A margem volta a subir com a nova logística\nO consumo de baixa renda segue fraco em 2027")
    t1, t2, _ = st.columns([1.2, 1.4, 3])
    t1.button("Sugerir teses com IA", on_click=_fill_theses, disabled=not ai_available(), use_container_width=True)
    with t2.popover("Premissas de mercado", use_container_width=True):
        rf = st.number_input("Taxa livre de risco %", value=MARKET_DEFAULTS["rf"] * 100, step=0.25,
                             help="Média da Selic esperada no Focus (23/10/2026) para 2026–2029")
        erp = st.number_input("Prêmio de risco de mercado %", value=MARKET_DEFAULTS["erp"] * 100, step=0.25,
                              help="Damodaran, prêmio implícito de jan/2026")
        g = st.number_input("Crescimento na perpetuidade %", value=MARKET_DEFAULTS["g"] * 100, step=0.25)
        spread = st.number_input("Spread da dívida %", value=MARKET_DEFAULTS["kd_spread"] * 100, step=0.25)
        tax = st.number_input("IR/CS %", value=MARKET_DEFAULTS["tax"] * 100, step=1.0)
        beta_in = st.number_input("Beta (0 = calcular contra o Ibovespa)", value=0.0, step=0.05)
    market = {"rf": rf / 100, "erp": erp / 100, "g": g / 100, "kd_spread": spread / 100, "tax": tax / 100}
    beta = beta_in if beta_in > 0 else None
    theses = [t for t in ss.get("theses_text", "").splitlines() if t.strip()]
    if st.button("Transformar teses em premissas", type="primary"):
        with st.spinner("Traduzindo teses e rodando o DCF…"):
            ss.val = build_valuation(res, theses, market=market, beta=beta)
        ss.pop("val_files", None)
        st.rerun()

    val = ss.get("val")
    if val is None:
        st.markdown("<p class='hint' style='margin-top:14px'>Sem teses, o modelo usa premissas simples tiradas do "
                    "histórico: crescimento convergindo para inflação + 1% real e margem do LTM.</p>",
                    unsafe_allow_html=True)
        return

    st.markdown("<div class='step'><span class='n'>2</span><span class='t'>Premissas por cenário</span></div>"
                f"<p class='hint'>Fonte: {val.assumptions_source}. Edite os números e recalcule; valores fora de faixa "
                "são ajustados e aparecem nos avisos.</p>", unsafe_allow_html=True)
    cols3 = st.columns(len(val.scenarios))
    edited = {}
    for col, (name, sc) in zip(cols3, val.scenarios.items()):
        with col, st.container(border=True):
            edited[name] = _scenario_editor(name, sc, f"sc_{name}")
    if st.button("Recalcular com as premissas editadas"):
        for k in edited:
            edited[k].terminal_growth = market["g"]
        ss.val = build_valuation(res, theses, scenarios=edited, market=market, beta=val.wacc.beta)
        ss.pop("val_files", None)
        st.rerun()

    st.markdown("<div class='step'><span class='n'>3</span><span class='t'>Resultado</span></div>", unsafe_allow_html=True)
    rec = val.recommendation
    cls = {"COMPRA": "buy", "VENDA": "sell"}.get(rec, "hold")
    st.markdown(
        f"<div class='rec {cls}'><div class='word'>{rec}</div>"
        f"<div class='num'>Preço-alvo<b>R$ {br(val.target_price, 2)}</b></div>"
        f"<div class='num'>Upside<b class='{ui.tone(val.upside)}'>{pc(val.upside, sign=True)}</b></div>"
        f"<div class='num'>Preço atual<b>R$ {br(val.price, 2)}</b></div>"
        f"<div class='num'>WACC<b>{pc(val.wacc.value)}</b></div></div>", unsafe_allow_html=True)
    st.caption(f"Preço-alvo = DCF do cenário base. COMPRA com upside de pelo menos {pc(BUY_UPSIDE)}, VENDA com "
               f"{pc(SELL_UPSIDE)} ou pior, NEUTRO entre os dois. Exercício acadêmico com dados públicos; "
               "não é recomendação de investimento.")

    ff = pd.DataFrame([{"Método": r.label, "Mín": r.low, "Máx": r.high, "Tipo": r.kind} for r in val.field])
    bars = alt.Chart(ff).mark_bar(height=22, cornerRadius=3).encode(
        y=alt.Y("Método:N", sort=None, title=None, axis=alt.Axis(labelColor=ui.TEXT, labelLimit=280, domain=False, ticks=False)),
        x=alt.X("Mín:Q", title="R$ por ação", axis=alt.Axis(format=".2f")),
        x2="Máx:Q",
        color=alt.Color("Tipo:N", legend=None, scale=alt.Scale(domain=["comps", "dcf", "mercado"],
                                                                 range=["#4A5562", ui.LINK, "#2E3843"])),
        tooltip=["Método", alt.Tooltip("Mín:Q", format=".2f"), alt.Tooltip("Máx:Q", format=".2f")])
    price_rule = alt.Chart(pd.DataFrame({"p": [val.price]})).mark_rule(color=ui.TEXT, strokeWidth=2).encode(x="p:Q")
    target_rule = alt.Chart(pd.DataFrame({"p": [val.target_price]})).mark_rule(color=ui.GREEN, strokeDash=[5, 4],
                                                                               strokeWidth=2).encode(x="p:Q")
    st.markdown("<div class='step'><span class='t'>Football field</span></div>"
                "<p class='hint'>Linha branca = preço atual; tracejada verde = preço-alvo.</p>", unsafe_allow_html=True)
    st.altair_chart(ui.dark_chart((bars + price_rule + target_rule).properties(height=46 * len(ff) + 30)),
                    use_container_width=True, theme=None)

    sm = summary(val).T
    st.dataframe(sm.style.format({
        "Crescimento médio": pc, "Margem EBITDA média": pc, "WACC": pc, "g perpetuidade": pc,
        "EV (R$ mi)": lambda v: br(v), "Equity (R$ mi)": lambda v: br(v),
        "Valor por ação (R$)": lambda v: f"R$ {br(v, 2)}", "Upside": lambda v: pc(v, sign=True),
        "% do EV na perpetuidade": lambda v: pc(v)}), use_container_width=True)
    with st.expander("Sensibilidade do cenário base (WACC nas linhas, g nas colunas)"):
        sens = val.sens.copy()
        sens.index = [pc(i) for i in sens.index]
        sens.columns = [pc(c) for c in sens.columns]
        st.dataframe(sens.style.format(lambda v: f"R$ {br(v, 2)}"), use_container_width=True)
    with st.expander("Fluxo de caixa do cenário base (R$ mi)"):
        st.dataframe(val.dcf["base"].table.style.format(lambda v: br(v, 2), na_rep=""), use_container_width=True)
    if val.warnings:
        with st.expander(f"Avisos do modelo ({len(val.warnings)})"):
            for w in val.warnings:
                st.markdown(f"- {w}")


def page_audit():
    page_header("Auditoria", "De qual documento e de qual conta da CVM saiu cada número, com link para o original.")
    if not need_result():
        return
    pick = st.selectbox("Empresa", list(res.financials), format_func=label, key="audit_pick")
    f = res.financials[pick]
    st.dataframe(pd.DataFrame([{"Métrica": a.metric, "R$ mi": a.value_mm, "Documento": a.document,
                                "Contas CVM": a.accounts, "Cálculo": a.formula, "Link": a.link} for a in f.audit]),
                 hide_index=True, use_container_width=True, height=420,
                 column_config={"R$ mi": st.column_config.NumberColumn(format="%.1f"),
                                "Link": st.column_config.LinkColumn(display_text="abrir na CVM")})
    warns = res.warnings()
    if warns:
        items = "".join(f"<li class='{'ex' if w.startswith('EXCLUÍDA') else ''}'><b>{t}</b>{w}</li>"
                        for t, ws_ in warns.items() for w in ws_)
        st.markdown("<div class='step'><span class='t'>Avisos de qualidade dos dados</span></div>"
                    f"<ul class='warnlist'>{items}</ul>", unsafe_allow_html=True)


def page_files():
    page_header("Arquivos", "Excel com fórmulas vivas e one-pager em PowerPoint, prontos para editar.")
    if not need_result():
        return
    stamp = date.today().strftime("%Y%m%d")
    if "files" not in ss:
        with st.spinner("Gerando o Excel de comps e o one-pager…"):
            xlsx = export_excel(res, OUTPUT_DIR / f"comps_{res.target}_{stamp}.xlsx")
            bullets, source = describe_business(res.companies[res.target])
            pptx = export_onepager(res, OUTPUT_DIR / f"onepager_{res.target}_{stamp}.pptx", bullets, source)
        ss.files = (xlsx, pptx, bullets, source)
    xlsx, pptx, bullets, source = ss.files
    XL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    PP = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    d1, d2 = st.columns(2, gap="medium")
    with d1, st.container(border=True):
        st.markdown("**Comparáveis**")
        st.download_button("Baixar Excel de comps", xlsx.read_bytes(), file_name=xlsx.name, mime=XL, use_container_width=True)
        st.download_button("Baixar one-pager (PowerPoint)", pptx.read_bytes(), file_name=pptx.name, mime=PP,
                           use_container_width=True)
    with d2, st.container(border=True):
        st.markdown("**Valuation por teses**")
        val = ss.get("val")
        if val is None:
            st.caption("Rode a página Valuation por teses para gerar o modelo e o slide com o football field.")
        else:
            if "val_files" not in ss:
                with st.spinner("Gerando o modelo de valuation…"):
                    mx = export_model(val, OUTPUT_DIR / f"modelo_{res.target}_{stamp}.xlsx", comps=res)
                    px = export_onepager(res, OUTPUT_DIR / f"pitch_{res.target}_{stamp}.pptx", bullets, source, valuation=val)
                ss.val_files = (mx, px)
            mx, px = ss.val_files
            st.download_button("Baixar modelo de valuation (Excel)", mx.read_bytes(), file_name=mx.name, mime=XL,
                               use_container_width=True)
            st.download_button("Baixar one-pager com football field", px.read_bytes(), file_name=px.name, mime=PP,
                               use_container_width=True)
    st.markdown("<div class='step'><span class='t'>Descrição do negócio usada no one-pager</span></div>",
                unsafe_allow_html=True)
    for b_ in bullets:
        st.markdown(f"- {b_}")
    st.caption(source)


with main:
    {"Comparar empresas": page_compare, "Valuation por teses": page_valuation,
     "Auditoria": page_audit, "Arquivos": page_files}[ss.page]()
