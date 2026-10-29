"""Acesso aos dados abertos da CVM (dados.cvm.gov.br).

Fontes usadas:
  - DFP  (Demonstrações Financeiras Padronizadas, anual)   -> DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip
  - ITR  (Informações Trimestrais)                          -> DOC/ITR/DADOS/itr_cia_aberta_{ano}.zip
  - FCA  (Formulário Cadastral: tickers, setor, descrição)  -> DOC/FCA/DADOS/fca_cia_aberta_{ano}.zip

Cada zip contém um CSV por demonstração (DRE, BPA, BPP, DVA, DFC_MI...), em versão
consolidada (_con) e individual (_ind), além do índice de documentos e da composição do capital.
Os CSVs vêm em latin-1, separados por ';'.
"""
from __future__ import annotations

import io
import logging
import time
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from .config import CACHE_MAX_AGE_DAYS, CVM_BASE, DATA_DIR

log = logging.getLogger(__name__)

STATEMENTS = ("DRE", "BPA", "BPP", "DVA", "DFC_MI")


def _to_float(col: pd.Series, default: float) -> pd.Series:
    """Texto -> float64 de verdade, inclusive em colunas vazias.

    No pandas 3 as colunas de texto usam o tipo string do Arrow; uma coluna vazia
    convertida com to_numeric pode continuar "string" e quebrar contas depois.
    """
    vals = pd.to_numeric(col.to_numpy(dtype=object), errors="coerce")
    return pd.Series(vals, index=col.index, dtype="float64").fillna(default)


class CVMDataUnavailable(Exception):
    """Arquivo da CVM não existe (ex.: ano ainda sem dados) ou não pôde ser baixado."""


class CVMRepository:
    """Baixa, guarda em cache e lê os arquivos da CVM.

    `offline=True` usa apenas o que já está em `data_dir` (útil para testes e para
    um demo sem internet).
    """

    def __init__(self, data_dir: Path | str = DATA_DIR, offline: bool = False):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self._frames: dict[tuple, pd.DataFrame] = {}
        self._missing: set[tuple] = set()   # arquivos que a CVM ainda não publicou (evita repetir o 404)

    # ------------------------------------------------------------------ download
    def _url(self, kind: str, year: int | None) -> str:
        if kind == "cad":
            return f"{CVM_BASE}/CAD/DADOS/cad_cia_aberta.csv"
        folder = kind.upper()
        return f"{CVM_BASE}/DOC/{folder}/DADOS/{kind}_cia_aberta_{year}.zip"

    def _local_path(self, kind: str, year: int | None) -> Path:
        name = "cad_cia_aberta.csv" if kind == "cad" else f"{kind}_cia_aberta_{year}.zip"
        return self.data_dir / name

    def _ensure(self, kind: str, year: int | None) -> Path:
        if (kind, year) in self._missing:
            raise CVMDataUnavailable(f"{kind} {year} indisponível")
        try:
            return self._download(kind, year)
        except CVMDataUnavailable:
            self._missing.add((kind, year))
            raise

    def _download(self, kind: str, year: int | None) -> Path:
        path = self._local_path(kind, year)
        max_age = CACHE_MAX_AGE_DAYS.get(kind, 7) * 86400
        fresh = path.exists() and (time.time() - path.stat().st_mtime) < max_age
        if fresh or (self.offline and path.exists()):
            return path
        if self.offline:
            raise CVMDataUnavailable(f"{path.name} não está no cache e o modo offline está ligado")
        import requests  # import tardio: os testes offline não precisam da lib

        url = self._url(kind, year)
        log.info("Baixando %s", url)
        try:
            resp = requests.get(url, timeout=120)
        except requests.RequestException as exc:
            if path.exists():  # sem internet: usa o cache antigo e avisa
                log.warning("Falha ao baixar %s (%s); usando cache de %s", url, exc, path)
                return path
            raise CVMDataUnavailable(f"Não foi possível baixar {url}: {exc}") from exc
        if resp.status_code == 404:
            raise CVMDataUnavailable(f"{url} não existe (ano sem dados?)")
        resp.raise_for_status()
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(resp.content)
        tmp.replace(path)
        return path

    # ------------------------------------------------------------------ leitura
    def _read_from_zip(self, kind: str, year: int, member: str) -> pd.DataFrame:
        key = (kind, year, member)
        if key in self._frames:
            return self._frames[key]
        path = self._ensure(kind, year)
        with zipfile.ZipFile(path) as zf:
            if member not in zf.namelist():
                raise CVMDataUnavailable(f"{member} não encontrado em {path.name}")
            raw = zf.read(member)
        df = pd.read_csv(io.BytesIO(raw), sep=";", encoding="latin-1", dtype=str, keep_default_na=False)
        df.columns = [c.strip() for c in df.columns]
        if "VL_CONTA" in df.columns:
            df["VL_CONTA"] = _to_float(df["VL_CONTA"], 0.0)
        if "VERSAO" in df.columns:
            df["VERSAO"] = _to_float(df["VERSAO"], 1.0).astype("int64")
        for col in df.columns:
            if col.startswith("QT_"):
                df[col] = _to_float(df[col], 0.0)
        self._frames[key] = df
        return df

    def statement(self, doc: str, year: int, stmt: str, consolidated: bool) -> pd.DataFrame:
        """Uma demonstração inteira (todas as empresas). doc = 'dfp' ou 'itr'."""
        suffix = "con" if consolidated else "ind"
        return self._read_from_zip(doc, year, f"{doc}_cia_aberta_{stmt}_{suffix}_{year}.csv")

    def doc_index(self, doc: str, year: int) -> pd.DataFrame:
        """Índice de documentos entregues (traz data de entrega e link para o documento no RAD/CVM)."""
        return self._read_from_zip(doc, year, f"{doc}_cia_aberta_{year}.csv")

    def capital(self, doc: str, year: int) -> pd.DataFrame:
        return self._read_from_zip(doc, year, f"{doc}_cia_aberta_composicao_capital_{year}.csv")

    def fca(self, year: int, table: str) -> pd.DataFrame:
        """Tabelas do Formulário Cadastral: 'geral', 'valor_mobiliario', 'endereco', ..."""
        return self._read_from_zip("fca", year, f"fca_cia_aberta_{table}_{year}.csv")

    def available(self, doc: str, year: int) -> bool:
        try:
            self._ensure(doc, year)
            return True
        except CVMDataUnavailable:
            return False


def years_to_try(today: date | None = None) -> list[int]:
    """Anos mais recentes primeiro (o DFP do ano corrente normalmente ainda não existe)."""
    today = today or date.today()
    return [today.year, today.year - 1, today.year - 2]
