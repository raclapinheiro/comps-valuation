"""Universo de empresas listadas: ticker <-> CNPJ, nome, setor e descrição (Formulário Cadastral da CVM)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .cvm import CVMDataUnavailable, CVMRepository, years_to_try


@dataclass
class Company:
    cnpj: str
    name: str
    sector: str = ""
    activity: str = ""
    website: str = ""
    tickers: dict[str, str] = field(default_factory=dict)  # classe ('ON', 'PN', 'UNIT') -> ticker

    @property
    def main_ticker(self) -> str:
        for cls in ("ON", "UNIT", "PN"):
            if cls in self.tickers:
                return self.tickers[cls]
        return next(iter(self.tickers.values()), "")


# Ticker da B3: 4 caracteres (o primeiro é letra; B3SA3 tem dígito na raiz) + 1 ou 2 dígitos.
_TICKER_RE = re.compile(r"[A-Z][A-Z0-9]{3}\d{1,2}")
FIXES_PATH = Path(__file__).with_name("ticker_fixes.csv")


def clean_ticker(code: object) -> str | None:
    """Normaliza o Codigo_Negociacao do FCA; devolve None se não for um ticker da B3.

    O campo é texto livre: há "tgma3" (minúsculo), "022055" (Marisa), "4030" (CSN), "ADR", "N/A".
    """
    t = str(code or "").strip().upper()
    return t if _TICKER_RE.fullmatch(t) else None


def _read_fixes(path: Path) -> dict[str, tuple[str, str]]:
    """Correções cnpj -> (ticker, nota). Arquivo com cabeçalho cnpj;ticker;nota."""
    out: dict[str, tuple[str, str]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8-sig").splitlines()[1:]:
        parts = [p.strip() for p in line.split(";")]
        if len(parts) >= 2 and clean_ticker(parts[1]):
            out[parts[0]] = (parts[1].upper(), parts[2] if len(parts) > 2 else "correção manual")
    return out


def _share_class(valor_mobiliario: str, ticker: str) -> str | None:
    v = valor_mobiliario.lower()
    if "unit" in v or ticker.endswith("11"):
        return "UNIT"
    if "ordin" in v or ticker.endswith("3"):
        return "ON"
    if "prefer" in v or re.search(r"[456]$", ticker):
        return "PN"
    return None


class Universe:
    def __init__(self, repo: CVMRepository):
        self.repo = repo
        self.companies: dict[str, Company] = {}
        self.by_ticker: dict[str, str] = {}
        self.old_tickers: dict[str, str] = {}   # códigos antigos -> CNPJ (mudança de ticker)
        self.bad_codes: dict[str, str] = {}     # código inválido no FCA -> CNPJ (ex.: "022055" da Marisa)
        self.ticker_notes: dict[str, str] = {}  # CNPJ -> de onde veio o ticker, quando foi corrigido
        self._load()

    def _load(self) -> None:
        # Junta os FCAs dos últimos anos; o mais recente de cada empresa prevalece.
        geral_frames, vm_frames = [], []
        for year in years_to_try():
            try:
                g = self.repo.fca(year, "geral")
                v = self.repo.fca(year, "valor_mobiliario")
            except CVMDataUnavailable:
                continue
            geral_frames.append(g)
            vm_frames.append(v)
        if not geral_frames:
            raise CVMDataUnavailable("Nenhum Formulário Cadastral (FCA) disponível")

        geral = pd.concat(geral_frames, ignore_index=True)
        geral = geral.sort_values(["Data_Referencia", "Versao"]).drop_duplicates("CNPJ_Companhia", keep="last")
        for _, r in geral.iterrows():
            if r.get("Situacao_Registro_CVM", "Ativo") not in ("Ativo", ""):
                continue
            self.companies[r["CNPJ_Companhia"]] = Company(
                cnpj=r["CNPJ_Companhia"],
                name=r["Nome_Empresarial"],
                sector=r.get("Setor_Atividade", ""),
                activity=r.get("Descricao_Atividade", ""),
                website=r.get("Pagina_Web", ""),
            )

        vm = pd.concat(vm_frames, ignore_index=True).astype(object)
        is_share = ["bolsa" in str(m).lower() and any(k in str(v).lower() for k in ("ordin", "prefer", "unit"))
                    for m, v in zip(vm["Mercado"], vm["Valor_Mobiliario"])]
        valid = [clean_ticker(t) is not None for t in vm["Codigo_Negociacao"]]
        for s, ok, t, cnpj in zip(is_share, valid, vm["Codigo_Negociacao"], vm["CNPJ_Companhia"]):
            if s and not ok and str(t).strip():
                self.bad_codes.setdefault(str(t).strip().upper(), cnpj)
        keep = [s and ok for s, ok in zip(is_share, valid)]
        # Negociação encerrada = data fim preenchida E posterior ao início. Há cadastros com
        # fim == início por erro de preenchimento (ex.: C&A, CEAB3), que seguem negociando.
        ended = [bool(str(f).strip()) and str(f) > str(i)
                 for f, i in zip(vm["Data_Fim_Negociacao"], vm["Data_Inicio_Negociacao"])]
        vm = vm[[k and not e for k, e in zip(keep, ended)]]
        latest = vm.groupby("CNPJ_Companhia")["Data_Referencia"].transform("max")

        # Ticker atual = documento mais recente. Tickers antigos continuam resolvendo para a
        # empresa (ex.: GUAR3 virou RIAA3 em 2026), mas a cotação usa o código atual.
        for is_latest, (_, r) in zip(vm["Data_Referencia"] == latest, vm.iterrows()):
            comp = self.companies.get(r["CNPJ_Companhia"])
            if comp is None:
                continue
            ticker = clean_ticker(r["Codigo_Negociacao"])
            if is_latest:
                cls = _share_class(str(r["Valor_Mobiliario"]), ticker)
                if cls and cls not in comp.tickers:
                    comp.tickers[cls] = ticker
                self.by_ticker[ticker] = comp.cnpj
            else:
                self.old_tickers.setdefault(ticker, comp.cnpj)

        # Empresas cujo FCA traz um código que não é ticker (ou nenhum): correções conhecidas
        # (comps/ticker_fixes.csv) e as do usuário (data/tickers_manuais.csv, que prevalecem).
        fixes = _read_fixes(FIXES_PATH) | _read_fixes(self.repo.data_dir / "tickers_manuais.csv")
        for cnpj, (ticker, note) in fixes.items():
            comp = self.companies.get(cnpj)
            if comp is None:
                continue
            cls = _share_class("", ticker) or "ON"
            for old in comp.tickers.values():
                self.old_tickers.setdefault(old, cnpj)
            comp.tickers = {cls: ticker}
            self.by_ticker[ticker] = cnpj
            self.ticker_notes[cnpj] = f"Ticker corrigido: {note}"

    # ------------------------------------------------------------------ consultas
    def resolve(self, ticker: str) -> Company:
        t = ticker.strip().upper().removesuffix(".SA")
        if t in self.by_ticker:
            return self.companies[self.by_ticker[t]]
        if t in self.old_tickers:
            return self.companies[self.old_tickers[t]]
        # Ticker de outra classe da mesma empresa (ex.: pediu PETR3 mas só PETR4 está no FCA)
        root = t[:4]
        for tk, cnpj in self.by_ticker.items():
            if tk.startswith(root):
                return self.companies[cnpj]
        if t in self.bad_codes and self.bad_codes[t] in self.companies:
            comp = self.companies[self.bad_codes[t]]
            if comp.tickers:            # já corrigido (ex.: 022055 -> AMAR3)
                return comp
            name = comp.name
            raise KeyError(f"{t} não é um ticker da B3: é o código que a {name} preencheu no Formulário "
                           f"Cadastral da CVM. Informe o ticker em data/tickers_manuais.csv (cnpj;ticker;nota).")
        raise KeyError(f"Ticker {ticker} não encontrado no Formulário Cadastral da CVM")

    def _active_cnpjs(self) -> set[str]:
        """Empresas que entregaram ITR ou DFP recentemente (evita sugerir quem saiu da bolsa)."""
        if not hasattr(self, "_active"):
            act: set[str] = set()
            for doc in ("itr", "dfp"):
                for year in years_to_try():
                    try:
                        act |= set(self.repo.doc_index(doc, year)["CNPJ_CIA"])
                        break
                    except CVMDataUnavailable:
                        continue
            self._active = act
        return self._active

    def listed(self, active_only: bool = True) -> list[Company]:
        act = self._active_cnpjs() if active_only else set()
        return [c for c in self.companies.values() if c.tickers and (not act or c.cnpj in act)]

    def same_sector(self, company: Company) -> list[Company]:
        return [c for c in self.listed() if c.sector == company.sector and c.cnpj != company.cnpj]

    def rule_peers(self, company: Company, n: int = 8) -> list[tuple[Company, str]]:
        """Peers sem IA: mesmo setor da CVM, ordenados pela semelhança da descrição da atividade.

        Ex.: para "Loja de Departamentos (Comércio Varejista)", outras lojas de departamento vêm
        antes de supermercados, que vêm antes de distribuidores. Exclui empresas em recuperação judicial.
        """
        def words(t: str) -> set[str]:
            return {w for w in re.findall(r"[a-zà-ú]{4,}", t.lower())}
        base = words(company.activity)
        scored = []
        for c in self.same_sector(company):
            if "RECUPERA" in c.name.upper():
                continue
            w = words(c.activity)
            sim = len(base & w) / len(base | w) if (base | w) else 0.0
            scored.append((1 if c.activity == company.activity else 0, sim, c))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2].name))
        out = []
        for same, sim, c in scored[:n]:
            why = "Mesma atividade na CVM" if same else ("Atividade parecida" if sim > 0 else "Mesmo setor na CVM")
            out.append((c, f"{why}: {c.activity}"))
        return out

    def search(self, text: str, limit: int = 10) -> list[Company]:
        q = text.strip().upper()
        hits = [c for c in self.listed() if q in c.name.upper() or any(q in t for t in c.tickers.values())]
        return hits[:limit]
