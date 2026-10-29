"""Camada de IA (Claude, da Anthropic).

Princípio de projeto: **números nunca passam pelo modelo**. A IA faz só o que é
linguagem e julgamento qualitativo:
  1) sugerir peers, ESCOLHENDO de uma lista fechada de empresas listadas que vem da CVM
     (o modelo não pode inventar empresa; o que vier fora da lista é descartado);
  2) escrever a descrição do negócio para o one-pager.
Os números do one-pager e do Excel vêm sempre do código determinístico.

Sem ANTHROPIC_API_KEY, tudo continua funcionando com regras simples (fallback).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

from .config import CLAUDE_MODEL
from .universe import Company, Universe

log = logging.getLogger(__name__)


@dataclass
class PeerSuggestion:
    ticker: str
    name: str
    reason: str


def ai_available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _ask(system: str, user: str, max_tokens: int = 1500) -> str:
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    raw = m.group(1) if m else text
    start = min([i for i in (raw.find("["), raw.find("{")) if i >= 0], default=0)
    return json.loads(raw[start:])


# ---------------------------------------------------------------------- peers
def suggest_peers(target: Company, universe: Universe, n: int = 8) -> list[PeerSuggestion]:
    candidates = universe.same_sector(target)
    if not ai_available() or not candidates:
        return _fallback_peers(target, candidates, n, universe)

    lista = "\n".join(f"- {c.main_ticker}: {c.name} | {c.activity}" for c in candidates)
    system = (
        "Você é analista de Investment Banking no Brasil montando uma tabela de comparáveis (trading comps). "
        "Escolha peers pelo modelo de negócio, canal, público, mix de produtos e porte; o setor da CVM é amplo demais. "
        "Responda SOMENTE com JSON."
    )
    user = (
        f"Empresa-alvo: {target.main_ticker} - {target.name} ({target.activity}).\n\n"
        f"Escolha até {n} peers SOMENTE desta lista (empresas listadas na B3, setor '{target.sector}' na CVM):\n{lista}\n\n"
        "Ordene do mais comparável para o menos comparável. Exclua empresas em recuperação judicial ou com "
        "modelo de negócio muito diferente. Formato:\n"
        '[{"ticker": "XXXX3", "motivo": "uma frase objetiva"}]'
    )
    try:
        data = _extract_json(_ask(system, user))
    except Exception as exc:  # noqa: BLE001 - qualquer falha da API cai no fallback
        log.warning("IA indisponível para peers (%s); usando regra simples", exc)
        return _fallback_peers(target, candidates, n, universe)

    valid = {c.main_ticker: c for c in candidates}
    out = []
    for item in data:
        t = str(item.get("ticker", "")).upper().strip()
        if t in valid and t not in {p.ticker for p in out}:   # trava: nada fora da lista da CVM
            out.append(PeerSuggestion(t, valid[t].name, str(item.get("motivo", ""))))
    return out[:n] or _fallback_peers(target, candidates, n, universe)


def _fallback_peers(target: Company, candidates: list[Company], n: int, universe: Universe | None = None) -> list[PeerSuggestion]:
    """Sem IA: ranking por semelhança da atividade dentro do setor (Universe.rule_peers)."""
    if universe is not None:
        return [PeerSuggestion(c.main_ticker, c.name, why) for c, why in universe.rule_peers(target, n)]
    same = [c for c in candidates if c.activity == target.activity]
    rest = [c for c in candidates if c.activity != target.activity and "RECUPERA" not in c.name.upper()]
    return [PeerSuggestion(c.main_ticker, c.name, f"Mesmo setor CVM ({c.activity})") for c in (same + rest)[:n]]


# ---------------------------------------------------------------------- descrição
def _fallback_description(company: Company) -> tuple[list[str], str]:
    return ([f"{company.name.title()}: {company.activity}.",
             f"Setor de atuação (CVM): {company.sector}."],
            "CVM (Formulário Cadastral); descrição completa requer a camada de IA")


def describe_business(company: Company, context: str = "") -> tuple[list[str], str]:
    """Retorna (bullets, fonte). `context` pode trazer texto público (ex.: release, site de RI)."""
    if not ai_available():
        return _fallback_description(company)
    system = (
        "Você escreve one-pagers de Investment Banking em português, tom sóbrio e factual. "
        "Não use NENHUM número (receita, lojas, market share, datas, percentuais): os números do slide vêm de outra fonte "
        "auditada. Se não tiver certeza sobre algo, não escreva. Responda SOMENTE com JSON."
    )
    extra = "Contexto adicional:\n" + context + "\n" if context else ""
    user = (
        f"Empresa: {company.name} (ticker {company.main_ticker}). Atividade segundo a CVM: {company.activity}. "
        f"Setor: {company.sector}.\n{extra}"
        "Escreva 4 bullets curtos (máx. 22 palavras cada) cobrindo: o que a empresa faz e para quem; "
        "marcas/formatos/canais; diferenciais competitivos; temas estratégicos atuais. Formato: "
        '{"bullets": ["...", "...", "...", "..."]}'
    )
    try:
        data = _extract_json(_ask(system, user, max_tokens=800))
        bullets = [re.sub(r"\s+", " ", b).strip() for b in data["bullets"]][:4]
        # Segunda trava: se escapou algum número, descarta o bullet
        bullets = [b for b in bullets if not re.search(r"\d", b)]
        if bullets:
            return bullets, f"Gerado por IA ({CLAUDE_MODEL}), revisar antes de enviar"
    except Exception as exc:  # noqa: BLE001
        log.warning("IA indisponível para descrição (%s)", exc)
    return _fallback_description(company)


# ---------------------------------------------------------------------- teses -> premissas
def suggest_theses(company: Company, hist_text: str) -> list[str]:
    """Pontos de partida para o analista: 2 teses positivas e 2 negativas, em texto (sem números)."""
    if not ai_available():
        return []
    system = ("Você é analista de equity research cobrindo empresas brasileiras. Responda SOMENTE com JSON. "
              "Não use números nas teses.")
    user = (f"Empresa: {company.name} ({company.main_ticker}), {company.activity}.\nHistórico (R$ milhões):\n{hist_text}\n\n"
            "Liste 2 teses positivas e 2 negativas que um investidor discutiria hoje, uma frase cada. "
            'Formato: {"teses": ["...", "...", "...", "..."]}')
    try:
        data = _extract_json(_ask(system, user, max_tokens=600))
        return [re.sub(r"\s+", " ", t).strip() for t in data["teses"] if not re.search(r"\d", t)][:6]
    except Exception as exc:  # noqa: BLE001
        log.warning("IA indisponível para teses (%s)", exc)
        return []


def propose_assumptions(company: Company, hist_text: str, theses: list[str], defaults: dict) -> tuple[dict, str]:
    """A IA traduz teses qualitativas em PREMISSAS (entradas do modelo), nunca em resultados.

    Devolve ({cenário: {growth[5], margin[5], capex_pct, nwc_pct, rationale{}, theses_used[]}}, fonte).
    Quem calcula o DCF é o código; quem valida limites é dcf.validate; quem aprova é o analista.
    """
    if not ai_available() or not theses:
        return {}, "regra simples (sem IA)"
    lista = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(theses))
    system = (
        "Você é analista de valuation num banco de investimento brasileiro. Sua tarefa é traduzir teses de "
        "investimento em premissas de um modelo de fluxo de caixa descontado. Você NÃO calcula valuation. "
        "Seja coerente com o histórico informado e com as teses; cada premissa deve citar as teses que a justificam. "
        "Valores em decimal (0,08 = 8%). Responda SOMENTE com JSON."
    )
    user = (
        f"Empresa: {company.name} ({company.main_ticker}), {company.activity}.\n"
        f"Histórico (R$ milhões; EBITDA ex-IFRS16 = EBITDA - pagamentos de aluguel):\n{hist_text}\n\n"
        f"Premissas de referência sem teses (regra simples): {json.dumps(defaults)}\n\n"
        f"Teses do analista:\n{lista}\n\n"
        "Para os cenários pessimista, base e otimista, proponha para os próximos 5 anos: crescimento nominal da "
        "receita (inflação incluída), margem EBITDA ex-IFRS16, capex/receita e capital de giro/receita. "
        "O pessimista deve ficar abaixo do base e o otimista acima. Formato exato:\n"
        '{"cenarios": {"base": {"crescimento": [5 valores], "margem": [5 valores], "capex_pct": x, "capital_giro_pct": x, '
        '"teses": [números das teses usadas], "justificativa": {"crescimento": "...", "margem": "...", '
        '"capex": "...", "capital de giro": "..."}}, "pessimista": {...}, "otimista": {...}}}'
    )
    try:
        data = _extract_json(_ask(system, user, max_tokens=2500))["cenarios"]
    except Exception as exc:  # noqa: BLE001
        log.warning("IA indisponível para premissas (%s)", exc)
        return {}, "regra simples (IA indisponível)"

    out = {}
    for name in ("pessimista", "base", "otimista"):
        c = data.get(name) or {}
        try:
            g = [float(x) for x in c["crescimento"]][:5]
            m = [float(x) for x in c["margem"]][:5]
            if len(g) != 5 or len(m) != 5:
                raise ValueError("listas com tamanho errado")
            # A IA às vezes manda 8 em vez de 0,08: normaliza percentuais escritos como inteiros
            g = [x / 100 if abs(x) > 1 else x for x in g]
            m = [x / 100 if abs(x) > 1 else x for x in m]
            capex = float(c.get("capex_pct", defaults["capex_pct"]))
            nwc = float(c.get("capital_giro_pct", defaults["nwc_pct"]))
            capex = capex / 100 if capex > 1 else capex
            nwc = nwc / 100 if abs(nwc) > 2 else nwc
            used = [int(i) for i in c.get("teses", []) if 1 <= int(i) <= len(theses)]
            just = {str(k): str(v) for k, v in (c.get("justificativa") or {}).items()}
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("Premissa inválida da IA para %s (%s)", name, exc)
            return {}, "regra simples (resposta da IA inválida)"
        out[name] = {"growth": g, "margin": m, "capex_pct": capex, "nwc_pct": nwc,
                     "rationale": just, "theses_used": used}
    return out, f"IA ({CLAUDE_MODEL}) a partir das teses, validada pelo código"
