"""Peças visuais do app (tema escuro): CSS, formatação pt-BR e blocos HTML.

Fica separado do app.py para dar para testar e pré-visualizar o HTML sem o Streamlit.
"""
from __future__ import annotations

from datetime import timedelta
from html import escape

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------- paleta
BG, SURFACE, SURFACE2, LINE = "#0F1418", "#1B2127", "#232A31", "#2D353D"
TEXT, MUTED, FAINT = "#EEF1F4", "#A3ADB7", "#6E7882"
LINK, GREEN, RED, ACCENT = "#7AB0FF", "#2BC275", "#FF5B6B", "#14A866"
NAV_ON_BG, NAV_ON = "#1E3557", "#A9CBFF"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700;800&display=swap');
:root {{ color-scheme: dark; }}
html, body, .stApp, .stMarkdown, button, input, textarea, select, [data-baseweb] {{
  font-family: 'Figtree', system-ui, sans-serif; }}
.stApp {{ background: {BG}; color: {TEXT}; }}
header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {{ display: none !important; }}
.block-container {{ padding: 0.9rem 1.6rem 4rem 1.6rem; max-width: 1560px; }}
h1, h2, h3, h4 {{ color: {TEXT}; letter-spacing: -0.01em; }}
a {{ color: {LINK}; }}
p, li {{ color: {TEXT}; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: {MUTED} !important; }}

/* ---------- barra superior */
.brand {{ display: flex; align-items: baseline; gap: 8px; white-space: nowrap; }}
.brand .w1 {{ font-size: 23px; font-weight: 800; color: {TEXT}; letter-spacing: -0.02em; }}
.brand .w2 {{ font-size: 23px; font-weight: 500; color: {MUTED}; letter-spacing: -0.02em; }}
.topline {{ border-bottom: 1px solid {LINE}; margin: 10px -1.6rem 18px -1.6rem; }}
.topmeta {{ color: {MUTED}; font-size: 13px; text-align: right; line-height: 1.35; }}
.st-key-target div[data-baseweb="select"] > div {{
  background: {SURFACE2}; border: 1px solid {SURFACE2}; border-radius: 999px; min-height: 46px; padding-left: 10px; }}
.st-key-target div[data-baseweb="select"] > div:hover {{ border-color: {LINE}; }}
.st-key-target div[data-baseweb="select"] span, .st-key-target div[data-baseweb="select"] input {{ font-size: 16px; }}
.stButton button[kind="primary"], .stDownloadButton button[kind="primary"] {{
  background: {ACCENT}; border: none; border-radius: 999px; font-weight: 700; color: #fff; min-height: 46px; }}
.stButton button[kind="primary"]:hover {{ background: #18BE74; color: #fff; }}
.stButton button[kind="secondary"], .stDownloadButton button, [data-testid="stPopover"] button {{
  background: {SURFACE}; border: 1px solid {LINE}; border-radius: 10px; color: {TEXT}; font-weight: 600; }}
.stButton button[kind="secondary"]:hover, .stDownloadButton button:hover, [data-testid="stPopover"] button:hover {{
  border-color: {FAINT}; color: #fff; }}

/* ---------- navegação lateral (rádio sem bolinha) */
.st-key-page div[role="radiogroup"] {{ gap: 2px; }}
.st-key-page div[role="radiogroup"] label {{
  padding: 8px 12px; border-radius: 8px; margin: 0; width: 100%; cursor: pointer; }}
.st-key-page div[role="radiogroup"] label > div:first-child {{ display: none; }}
.st-key-page div[role="radiogroup"] label p {{ font-size: 15.5px; font-weight: 600; color: {TEXT}; }}
.st-key-page div[role="radiogroup"] label:hover {{ background: {SURFACE}; }}
.st-key-page div[role="radiogroup"] label:has(input:checked) {{ background: {NAV_ON_BG}; }}
.st-key-page div[role="radiogroup"] label:has(input:checked) p {{ color: {NAV_ON}; }}
.navnote {{ color: {FAINT}; font-size: 12.5px; margin: 18px 12px 0 12px; line-height: 1.45; }}

/* ---------- cabeçalho de página */
.ph {{ font-size: 30px; font-weight: 800; letter-spacing: -0.02em; margin: 2px 0 2px 0; color: {TEXT}; }}
.psub {{ color: {MUTED}; font-size: 15px; margin: 0 0 14px 0; max-width: 70ch; }}
.pill {{ display: inline-flex; align-items: center; gap: 8px; border: 1px solid {LINE}; border-radius: 999px;
  padding: 7px 14px; font-size: 14px; font-weight: 600; color: {TEXT}; background: {SURFACE}; }}
.intro {{ color: {TEXT}; font-size: 15.5px; line-height: 1.45; margin: 4px 0 12px 0; }}

/* ---------- cartões das empresas */
.cards {{ display: flex; gap: 12px; overflow-x: auto; padding-bottom: 6px; scrollbar-width: thin; }}
.card {{ flex: 0 0 160px; background: {SURFACE}; border-radius: 10px; padding: 13px 15px; min-height: 96px;
  border: 1px solid transparent; position: relative; }}
.card.tgt {{ border-color: {LINK}; }}
.card .tk {{ color: {LINK}; font-weight: 700; font-size: 15px; }}
.card .role {{ position: absolute; right: 12px; top: 13px; font-size: 11.5px; font-weight: 700; color: {NAV_ON};
  background: {NAV_ON_BG}; padding: 2px 8px; border-radius: 999px; }}
.card .nm {{ color: {MUTED}; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.card .px {{ font-size: 19px; font-weight: 700; margin-top: 8px; font-variant-numeric: tabular-nums; }}
.card .ch {{ font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }}
.up {{ color: {GREEN} !important; }} .down {{ color: {RED} !important; }} .flat {{ color: {MUTED} !important; }}

/* ---------- tabela comparativa */
.cmp-wrap {{ overflow-x: auto; margin: 14px 0 26px 0; }}
.sec {{ margin-bottom: 22px; }}
.sec > summary {{ list-style: none; cursor: pointer; display: flex; align-items: center; gap: 12px;
  font-size: 22px; font-weight: 800; letter-spacing: -0.015em; margin: 0 0 10px 0; color: {TEXT}; }}
.sec > summary::-webkit-details-marker {{ display: none; }}
.sec > summary .chev {{ width: 10px; height: 10px; border-right: 2.5px solid {MUTED}; border-bottom: 2.5px solid {MUTED};
  transform: rotate(-135deg); margin: 6px 4px 0 6px; transition: transform .15s; }}
.sec:not([open]) > summary .chev {{ transform: rotate(45deg); margin-top: -2px; }}
table.cmp {{ border-collapse: separate; border-spacing: 0; width: 100%; table-layout: fixed;
  border: 1px solid {LINE}; border-radius: 10px; overflow: hidden; font-variant-numeric: tabular-nums; }}
table.cmp th, table.cmp td {{ padding: 12px 16px; border-bottom: 1px solid {LINE}; font-size: 15px; white-space: nowrap;
  text-align: right; color: {TEXT}; }}
table.cmp tr:last-child td {{ border-bottom: none; }}
table.cmp th {{ font-size: 13.5px; font-weight: 700; color: {MUTED}; background: {BG}; }}
table.cmp th.co {{ color: {LINK}; font-size: 14.5px; }}
table.cmp th.co.tgt {{ box-shadow: inset 0 2px 0 {LINK}; }}
table.cmp .lab {{ text-align: left; position: sticky; left: 0; background: {BG}; font-weight: 500; z-index: 1; overflow: hidden; text-overflow: ellipsis; }}
table.cmp th.lab {{ color: {TEXT}; font-weight: 600; }}
table.cmp td.med, table.cmp th.med {{ background: {SURFACE}; color: {MUTED}; }}
table.cmp tbody tr:hover td {{ background: {SURFACE}; }}
table.cmp td.na {{ color: {FAINT}; }}
table.cmp td.hi {{ color: {GREEN}; font-weight: 700; }}
table.cmp td.lo {{ color: {RED}; font-weight: 700; }}
table.cmp td .sub {{ display: block; color: {FAINT}; font-size: 12px; }}

/* ---------- coluna da direita */
.rail {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px; padding: 16px 16px 8px 16px; margin-bottom: 16px; }}
.rail h4 {{ font-size: 19px; font-weight: 800; margin: 0 0 10px 0; padding: 0; }}
.rrow {{ display: grid; grid-template-columns: minmax(0, 1fr) 74px 78px; align-items: center; gap: 8px;
  padding: 8px 0; border-top: 1px solid {LINE}; }}
.rrow:first-of-type {{ border-top: none; }}
.rrow .tk {{ color: {LINK}; font-weight: 700; font-size: 14px; }}
.rrow .nm {{ color: {TEXT}; font-size: 12.5px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.rrow .px {{ text-align: right; font-weight: 700; font-size: 14px; font-variant-numeric: tabular-nums; }}
.rrow .ch {{ text-align: right; font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }}
.rmuted {{ color: {MUTED}; font-size: 13.5px; line-height: 1.5; margin: 0 0 10px 0; }}
.kv {{ display: flex; justify-content: space-between; padding: 7px 0; border-top: 1px solid {LINE}; font-size: 14px; }}
.kv span:first-child {{ color: {MUTED}; }} .kv b {{ font-variant-numeric: tabular-nums; }}

/* ---------- recomendação */
.rec {{ display: flex; flex-wrap: wrap; align-items: center; gap: 34px; padding: 20px 24px; border-radius: 12px;
  margin: 8px 0 10px 0; border: 1px solid {LINE}; background: {SURFACE}; }}
.rec .word {{ font-size: 34px; font-weight: 800; letter-spacing: .01em; }}
.rec .num {{ font-size: 13.5px; color: {MUTED}; }}
.rec .num b {{ font-size: 23px; display: block; color: {TEXT}; font-variant-numeric: tabular-nums; }}
.rec.buy {{ border-color: rgba(43,194,117,.45); background: rgba(43,194,117,.08); }} .rec.buy .word {{ color: {GREEN}; }}
.rec.sell {{ border-color: rgba(255,91,107,.45); background: rgba(255,91,107,.08); }} .rec.sell .word {{ color: {RED}; }}
.rec.hold .word {{ color: {TEXT}; }}
.recmini {{ font-size: 26px; font-weight: 800; margin: 2px 0 6px 0; }}

.step {{ display: flex; gap: 12px; align-items: baseline; margin: 24px 0 6px 0; }}
.step .n {{ color: {LINK}; font-weight: 800; font-size: 18px; }}
.step .t {{ font-size: 20px; font-weight: 800; }}
.hint {{ color: {MUTED}; font-size: 14.5px; margin: 0 0 10px 0; max-width: 78ch; }}
.banner {{ border: 1px solid {LINE}; background: {SURFACE}; border-radius: 10px; padding: 12px 16px; color: {TEXT};
  font-size: 14.5px; margin: 6px 0 4px 0; }}
.banner b {{ color: {NAV_ON}; }}
.warnlist {{ margin: 0; padding: 0; list-style: none; }}
.warnlist li {{ padding: 10px 0; border-top: 1px solid {LINE}; font-size: 14.5px; color: {TEXT}; }}
.warnlist li b {{ color: {LINK}; margin-right: 6px; }}
.warnlist li.ex b {{ color: {RED}; }}

div[data-testid="stVerticalBlockBorderWrapper"] {{ border-color: {LINE} !important; background: {SURFACE}; border-radius: 12px; }}
div[data-testid="stExpander"] details {{ border-color: {LINE}; background: {SURFACE}; border-radius: 10px; }}
div[data-testid="stPopoverBody"] {{ background: {SURFACE}; border: 1px solid {LINE}; }}
.stTextArea textarea, .stNumberInput input {{ background: {SURFACE2}; }}
.st-key-peers_ms span[data-baseweb="tag"] {{ background: {NAV_ON_BG}; }}
.st-key-peers_ms span[data-baseweb="tag"] span {{ color: {NAV_ON}; }}
</style>
"""


# ---------------------------------------------------------------------- formatação pt-BR
def _nan(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or (not isinstance(v, str) and pd.isna(v))


def br(v, dec: int = 0) -> str:
    if _nan(v):
        return "n.m."
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def mm(v) -> str:
    return "n.m." if _nan(v) else (f"R$ {br(v / 1000, 1)} bi" if abs(v) >= 1000 else f"R$ {br(v)} mi")


def xx(v) -> str:
    return "n.m." if _nan(v) else f"{br(v, 1)}x"


def pc(v, sign: bool = False) -> str:
    if _nan(v):
        return "n.m."
    return (f"{v * 100:+.1f}%" if sign else f"{v * 100:.1f}%").replace(".", ",")


def short_name(name: str) -> str:
    n = name.title()
    for s in (" S.A.", " S.a.", " S/A", " Sa"):
        n = n.replace(s, "")
    return n.strip()


def tone(v) -> str:
    if _nan(v) or abs(v) < 1e-9:
        return "flat"
    return "up" if v > 0 else "down"


# ---------------------------------------------------------------------- preço
def performance(hist: pd.Series | None) -> dict[str, float]:
    """Variação do preço: dia, 1 semana, 3 meses, no ano e 12 meses (série de fechamentos diários)."""
    out = {k: np.nan for k in ("dia", "1 semana", "3 meses", "No ano", "12 meses")}
    if hist is None or len(hist) < 2:
        return out
    h = hist.dropna().sort_index()
    h.index = pd.to_datetime(h.index)
    last_d, last = h.index[-1], h.iloc[-1]

    def back(delta: timedelta) -> float:
        prev = h[h.index <= last_d - delta]
        return last / prev.iloc[-1] - 1 if not prev.empty else np.nan

    out["dia"] = last / h.iloc[-2] - 1
    out["1 semana"] = back(timedelta(days=7))
    out["3 meses"] = back(timedelta(days=91))
    prev_year = h[h.index.year < last_d.year]
    out["No ano"] = last / prev_year.iloc[-1] - 1 if not prev_year.empty else np.nan
    out["12 meses"] = last / h.iloc[0] - 1 if (last_d - h.index[0]).days >= 330 else np.nan
    return out


def sparkline(hist: pd.Series | None, days: int = 91, w: int = 74, h: int = 30) -> str:
    """SVG pequeno com os últimos ~3 meses; verde se subiu no período, vermelho se caiu."""
    if hist is None or len(hist) < 5:
        return f"<svg width='{w}' height='{h}'></svg>"
    s = hist.dropna().sort_index()
    s.index = pd.to_datetime(s.index)
    s = s[s.index >= s.index[-1] - timedelta(days=days)]
    if len(s) < 3:
        return f"<svg width='{w}' height='{h}'></svg>"
    lo, hi = float(s.min()), float(s.max())
    span = (hi - lo) or 1.0
    xs = np.linspace(1, w - 1, len(s))
    ys = [h - 2 - (float(v) - lo) / span * (h - 4) for v in s]
    color = GREEN if s.iloc[-1] >= s.iloc[0] else RED
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    base = ys[0]
    area = f"1,{h} " + pts + f" {w - 1},{h}"
    return (f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}' aria-hidden='true'>"
            f"<polygon points='{area}' fill='{color}' fill-opacity='0.13'/>"
            f"<line x1='0' x2='{w}' y1='{base:.1f}' y2='{base:.1f}' stroke='{MUTED}' stroke-width='1' "
            f"stroke-dasharray='2 3' opacity='0.6'/>"
            f"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='1.6' stroke-linejoin='round'/></svg>")


# ---------------------------------------------------------------------- blocos
def brand() -> str:
    return f"<div class='brand'><span class='w1'>Comps</span><span class='w2'>&amp; Valuation</span></div>"


def company_cards(items: list[dict]) -> str:
    """items: ticker, name, role ('Alvo'/'Peer'), price, change (variação do dia) — preço pode faltar."""
    out = []
    for it in items:
        tgt = it.get("role") == "Alvo"
        px = it.get("price")
        ch = it.get("change")
        px_html = f"R$ {br(px, 2)}" if not _nan(px) else "--"
        ch_html = (f"<div class='ch {tone(ch)}'>{pc(ch, sign=True)} no dia</div>" if not _nan(ch)
                   else "<div class='ch flat'>&nbsp;</div>")
        out.append(
            f"<div class='card{' tgt' if tgt else ''}'>"
            f"{'<span class=role>Alvo</span>' if tgt else ''}"
            f"<div class='tk'>{escape(it['ticker'])}</div><div class='nm' title='{escape(it['name'])}'>{escape(it['name'])}</div>"
            f"<div class='px'>{px_html}</div>{ch_html}</div>")
    return "<div class='cards'>" + "".join(out) + "</div>"


def compare_table(columns: list[dict], sections: list[tuple[str, list[tuple]]], corner: str,
                  highlight: bool = False, median: dict | None = None) -> str:
    """Tabela comparativa por seções recolhíveis.

    columns: [{ticker, target(bool)}]
    sections: [(título, [(rótulo, chave, formatador, maior_é_melhor|None)])]
    Cada coluna traz os valores em columns[i]['values'][chave]; median[chave] vai na última coluna.
    """
    head = (f"<tr><th class='lab'>{escape(corner)}</th>"
            + "".join(f"<th class='co{' tgt' if c.get('target') else ''}'>{escape(c['ticker'])}</th>" for c in columns)
            + ("<th class='med'>Mediana peers</th>" if median is not None else "") + "</tr>")
    ncols = len(columns) + (1 if median is not None else 0)
    colgroup = "<colgroup><col style='width:215px'>" + "<col>" * ncols + "</colgroup>"
    html = ["<div class='cmp-wrap'>"]
    for title, rows in sections:
        body = []
        for label, key, fmt, _better in rows:
            vals = [c.get("values", {}).get(key) for c in columns]
            nums = [v for v in vals if isinstance(v, (int, float, np.floating)) and not _nan(v)]
            # Destaque: verde = melhor, vermelho = pior (para múltiplos, menor é melhor). Só em linhas
            # em que "melhor" faz sentido; valor de mercado, preço etc. ficam neutros.
            hi = lo = None
            if highlight and _better is not None and len(nums) >= 2 and max(nums) != min(nums):
                hi, lo = (max(nums), min(nums)) if _better else (min(nums), max(nums))
            tds = []
            for v in vals:
                if v is None or (not isinstance(v, str) and _nan(v)):
                    tds.append("<td class='na'>--</td>")
                    continue
                txt = fmt(v) if fmt else escape(str(v))
                cls = ""
                if isinstance(v, (int, float, np.floating)):
                    cls = "hi" if (hi is not None and v == hi) else ("lo" if (lo is not None and v == lo) else "")
                    if txt == "n.m.":
                        cls = "na"
                tds.append(f"<td class='{cls}'>{txt}</td>")
            if median is not None:
                m = median.get(key)
                tds.append("<td class='med'>" + ("--" if m is None or (not isinstance(m, str) and _nan(m))
                                                  else (fmt(m) if fmt else escape(str(m)))) + "</td>")
            body.append(f"<tr><td class='lab'>{escape(label)}</td>{''.join(tds)}</tr>")
        html.append(f"<details class='sec' open><summary><span class='chev'></span>{escape(title)}</summary>"
                    f"<table class='cmp' style='min-width:{215 + 116 * ncols}px'>{colgroup}<thead>{head}</thead><tbody>{''.join(body)}</tbody></table></details>")
    html.append("</div>")
    return "".join(html)


SECTIONS: list[tuple[str, list[tuple]]] = [
    ("Valor de mercado", [
        ("Valor de mercado", "Valor de Mercado", mm, None),
        ("Enterprise value (EV)", "EV", mm, None),
        ("Preço da ação", "Preço (R$)", lambda v: f"R$ {br(v, 2)}", None),
        ("Período dos números", "Período", None, None),
        ("Base das demonstrações", "Base", None, None),
    ]),
    ("Desempenho do preço", [
        ("1 semana", "1 semana", lambda v: pc(v, sign=True), True),
        ("3 meses", "3 meses", lambda v: pc(v, sign=True), True),
        ("No ano", "No ano", lambda v: pc(v, sign=True), True),
        ("12 meses", "12 meses", lambda v: pc(v, sign=True), True),
    ]),
    ("Múltiplos", [
        ("EV / Receita", "EV/Receita", xx, False),
        ("EV / EBITDA", "EV/EBITDA", xx, False),
        ("EV / EBITDA ex-IFRS 16", "EV/EBITDA ex-IFRS16", xx, False),
        ("EV / EBIT", "EV/EBIT", xx, False),
        ("Preço / Lucro", "P/L", xx, False),
    ]),
    ("Resultado LTM", [
        ("Receita líquida", "Receita LTM", mm, True),
        ("Lucro bruto", "Lucro Bruto LTM", mm, True),
        ("EBITDA", "EBITDA LTM", mm, True),
        ("EBIT", "EBIT LTM", mm, True),
        ("Lucro líquido", "Lucro Líquido LTM", mm, True),
        ("Crescimento da receita no ano", "Cresc. Receita", pc, True),
    ]),
    ("Margens", [
        ("Margem bruta", "Margem Bruta", pc, True),
        ("Margem EBITDA", "Margem EBITDA", pc, True),
        ("Margem líquida", "Margem Líquida", pc, True),
    ]),
    ("Endividamento", [
        ("Dívida líquida ex-arrend.", "Dívida Líquida", mm, False),
        ("Arrendamentos (IFRS 16)", "Arrendamentos", mm, None),
        ("Minoritários", "Minoritários", mm, None),
        ("Dív. líq. / EBITDA ex-IFRS 16", "Dív. Líq./EBITDA ex-IFRS16", xx, False),
    ]),
]


def comps_columns(res) -> tuple[list[dict], dict]:
    """Converte o CompsResult em colunas da tabela comparativa (+ mediana dos peers)."""
    cols = []
    for _, r in res.table.iterrows():
        q = res.quotes.get(r["Ticker"])
        vals = r.to_dict()
        if not vals.get("Lucro Bruto LTM"):          # zero = conta não informada
            vals["Lucro Bruto LTM"] = np.nan
        vals.update(performance(q.history if q is not None else None))
        cols.append({"ticker": r["Ticker"], "target": r["Papel"] == "Alvo", "values": vals})
    med: dict = {}
    if "Mediana" in res.stats.index:
        med = res.stats.loc["Mediana"].to_dict()
    peers = [c["values"] for c in cols if not c["target"]]
    for k in ("1 semana", "3 meses", "No ano", "12 meses", "Preço (R$)"):
        xs = [p.get(k) for p in peers if not _nan(p.get(k))]
        if k != "Preço (R$)" and xs:
            med[k] = float(np.median(xs))
    for k in ("Lucro Bruto LTM", "EBIT LTM", "Lucro Líquido LTM", "Receita LTM", "EBITDA LTM", "Margem Bruta",
              "Margem Líquida", "Cresc. Receita", "EV/EBIT", "Dív. Líq./EBITDA ex-IFRS16", "Dívida Líquida",
              "Arrendamentos", "Minoritários", "Valor de Mercado", "EV", "EV/Receita", "EV/EBITDA",
              "EV/EBITDA ex-IFRS16", "P/L", "Margem EBITDA"):
        if k not in med:
            xs = [p.get(k) for p in peers if isinstance(p.get(k), (int, float, np.floating)) and not _nan(p.get(k))]
            if xs:
                med[k] = float(np.median(xs))
    return cols, med


def rail_quotes(title: str, items: list[dict], empty: str = "") -> str:
    """Lista à direita: ticker, nome, sparkline, preço e variação do dia."""
    rows = []
    for it in items:
        px, ch = it.get("price"), it.get("change")
        rows.append(
            f"<div class='rrow'><div><div class='tk'>{escape(it['ticker'])}</div>"
            f"<div class='nm' title='{escape(it['name'])}'>{escape(it['name'])}</div></div>"
            f"<div>{sparkline(it.get('history'))}</div>"
            f"<div><div class='px'>{br(px, 2) if not _nan(px) else '--'}</div>"
            f"<div class='ch {tone(ch)}'>{pc(ch, sign=True) if not _nan(ch) else ''}</div></div></div>")
    inner = "".join(rows) if rows else f"<p class='rmuted'>{escape(empty)}</p>"
    return f"<div class='rail'><h4>{escape(title)}</h4>{inner}</div>"


def rail_box(title: str, body_html: str) -> str:
    return f"<div class='rail'><h4>{escape(title)}</h4>{body_html}</div>"


def kv(label: str, value: str) -> str:
    return f"<div class='kv'><span>{escape(label)}</span><b>{value}</b></div>"


def dark_chart(chart):
    """Configuração Altair para o fundo escuro."""
    return (chart.configure(background="transparent")
            .configure_axis(labelColor=MUTED, titleColor=MUTED, gridColor=LINE, domainColor=LINE, tickColor=LINE,
                            labelFont="Figtree", titleFont="Figtree", labelFontSize=12)
            .configure_text(font="Figtree")
            .configure_view(stroke=None))
