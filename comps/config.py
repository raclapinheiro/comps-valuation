"""Configurações centrais do projeto."""
from __future__ import annotations

import os
from pathlib import Path

# Carrega variáveis de um arquivo .env na raiz do projeto (ex.: ANTHROPIC_API_KEY=...), se existir
_ENV = Path(__file__).resolve().parent.parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# Onde os arquivos baixados da CVM ficam guardados (cache local)
DATA_DIR = Path(os.environ.get("COMPS_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
OUTPUT_DIR = Path(os.environ.get("COMPS_OUTPUT_DIR", Path(__file__).resolve().parent.parent / "output"))

CVM_BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA"

# Arquivos de ITR/FCA são atualizados semanalmente pela CVM; DFP de anos fechados quase não muda
CACHE_MAX_AGE_DAYS = {"itr": 3, "dfp": 15, "fca": 7, "cad": 7}

# Modelo da Anthropic usado na camada de IA (pode trocar via variável de ambiente)
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")

# Peers padrão para o demo de varejo (usados quando não há IA disponível)
DEMO_TARGET = "LREN3"
DEMO_PEERS = ["CEAB3", "RIAA3", "AZZA3", "VIVA3", "SBFG3", "MGLU3", "ASAI3", "GMAT3", "RADL3", "PGMN3"]
