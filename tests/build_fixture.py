"""Gera um mini "espelho" da CVM com números REAIS de 4 varejistas (DFP 2025 + ITR 2T26),
no formato exato dos arquivos de dados abertos, para testar o pipeline sem internet.

Os valores foram extraídos dos arquivos oficiais em 28/10/2026. Foram mantidas só as
contas que o pipeline usa, mais algumas linhas "armadilha" (trimestre isolado, outra
versão do documento, arrendamento a receber) para garantir que os filtros funcionam.

Casos cobertos:
  * Grupo Mateus  -> arrendamento DENTRO da dívida (2.01.04.03) e minoritários relevantes
  * Sendas (Assaí)-> só publica demonstração INDIVIDUAL; ações reportadas em MILHARES
  * Guararapes    -> D&A em duas linhas do DFC (imobilizado + direito de uso)
  * Vivara        -> valores em UNIDADE (não em milhares)
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

COS = {
    "M": ("24.990.777/0001-09", "GRUPO MATEUS S.A.", "024902"),
    "S": ("06.057.223/0001-71", "SENDAS DISTRIBUIDORA S.A.", "025372"),
    "G": ("08.402.943/0001-52", "GUARARAPES CONFECCOES S.A.", "005762"),
    "V": ("33.839.910/0001-11", "VIVARA PARTICIPAÇÕES S.A.", "024805"),
}
ESC = {"M": "MIL", "S": "MIL", "G": "MIL", "V": "UNIDADE"}
IND_ONLY = {"S"}

# doc | empresa | stmt | ordem(U/P) | ini | fim | conta | descrição | valor
DATA = """
dfp|M|DRE|U|2025-01-01|2025-12-31|3.01|Receita de Venda de Bens e/ou Serviços|38424403
dfp|M|DRE|U|2025-01-01|2025-12-31|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|2260989
dfp|M|DRE|U|2025-01-01|2025-12-31|3.11|Lucro/Prejuízo Consolidado do Período|1857293
dfp|M|DVA|U|2025-01-01|2025-12-31|7.04.01|Depreciação, Amortização e Exaustão|-539596
dfp|M|DFC_MI|U|2025-01-01|2025-12-31|6.01.01|Caixa Gerado nas Operações|2546657
dfp|M|DFC_MI|U|2025-01-01|2025-12-31|6.01.01.01|Depreciação e amortização|539596
dfp|M|DFC_MI|U|2025-01-01|2025-12-31|6.03.07|Pagamento passivo de arrendamento|-492404
itr|M|DRE|P|2025-01-01|2025-06-30|3.01|Receita de Venda de Bens e/ou Serviços|17110941
itr|M|DRE|U|2026-01-01|2026-06-30|3.01|Receita de Venda de Bens e/ou Serviços|19254731
itr|M|DRE|U|2026-04-01|2026-06-30|3.01|Receita de Venda de Bens e/ou Serviços|9999999
itr|M|DRE|P|2025-01-01|2025-06-30|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|1143036
itr|M|DRE|U|2026-01-01|2026-06-30|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|888511
itr|M|DRE|P|2025-01-01|2025-06-30|3.11|Lucro/Prejuízo Consolidado do Período|672098
itr|M|DRE|U|2026-01-01|2026-06-30|3.11|Lucro/Prejuízo Consolidado do Período|432868
itr|M|DRE|P|2025-01-01|2025-06-30|3.11.01|Atribuído a Sócios da Empresa Controladora|662439
itr|M|DRE|U|2026-01-01|2026-06-30|3.11.01|Atribuído a Sócios da Empresa Controladora|449686
itr|M|DRE|P|2025-01-01|2025-06-30|3.11.02|Atribuído a Sócios Não Controladores|9659
itr|M|DRE|U|2026-01-01|2026-06-30|3.11.02|Atribuído a Sócios Não Controladores|-16818
itr|M|DVA|P|2025-01-01|2025-06-30|7.04.01|Depreciação, Amortização e Exaustão|-218387
itr|M|DVA|U|2026-01-01|2026-06-30|7.04.01|Depreciação, Amortização e Exaustão|-336138
itr|M|DFC_MI|P|2025-01-01|2025-06-30|6.01.01.02|Depreciação e amortização|218387
itr|M|DFC_MI|U|2026-01-01|2026-06-30|6.01.01.02|Depreciação e amortização|336139
itr|M|DFC_MI|P|2025-01-01|2025-06-30|6.03.04|Pagamento passivo de arrendamento|-208669
itr|M|DFC_MI|U|2026-01-01|2026-06-30|6.03.04|Pagamento passivo de arrendamento|-301311
itr|M|BPA|U||2026-06-30|1.01.01|Caixa e Equivalentes de Caixa|1631590
itr|M|BPA|U||2026-06-30|1.01.02|Aplicações Financeiras|0
itr|M|BPA|U||2026-06-30|1.01.03|Contas a Receber|3959000
itr|M|BPA|U||2026-06-30|1.01.04|Estoques|5736000
itr|M|BPP|U||2026-06-30|2.01.02|Fornecedores|4791000
itr|M|DFC_MI|U|2026-01-01|2026-06-30|6.02.01|Aquisição de Imobilizado|-357000
itr|M|DFC_MI|U|2026-01-01|2026-06-30|6.02.02|Aquisição de intangível|-25000
itr|M|DFC_MI|U|2026-01-01|2026-06-30|6.02.04|Venda de imobilizado|102000
itr|M|BPP|U||2026-06-30|2.01.04|Empréstimos e Financiamentos|1529728
itr|M|BPP|U||2026-06-30|2.01.04.01|Empréstimos e Financiamentos|1117841
itr|M|BPP|U||2026-06-30|2.01.04.02|Debêntures|193720
itr|M|BPP|U||2026-06-30|2.01.04.03|Financiamento por Arrendamento|218167
itr|M|BPP|U||2026-06-30|2.02.01|Empréstimos e Financiamentos|1194648
itr|M|BPP|U||2026-06-30|2.02.01.01|Empréstimos e Financiamentos|167403
itr|M|BPP|U||2026-06-30|2.02.01.02|Debêntures|651882
itr|M|BPP|U||2026-06-30|2.02.01.03|Financiamento por Arrendamento|375363
itr|M|BPP|U||2026-06-30|2.03|Patrimônio Líquido Consolidado|12345241
itr|M|BPP|U||2026-06-30|2.03.09|Participação dos Acionistas Não Controladores|1160623
dfp|S|DRE|U|2025-01-01|2025-12-31|3.01|Receita de Venda de Bens e/ou Serviços|77307000
dfp|S|DRE|U|2025-01-01|2025-12-31|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|3623000
dfp|S|DRE|U|2025-01-01|2025-12-31|3.11|Lucro/Prejuízo do Período|497000
dfp|S|DVA|U|2025-01-01|2025-12-31|7.04.01|Depreciação, Amortização e Exaustão|-1755000
dfp|S|DFC_MI|U|2025-01-01|2025-12-31|6.01.01.04|Depreciação e Amortização|1755000
dfp|S|DFC_MI|U|2025-01-01|2025-12-31|6.03.09|Pagamentos de Passivo de Arrendamento|-325000
dfp|S|DFC_MI|U|2025-01-01|2025-12-31|6.03.10|Pagamento de Juros de Passivo de Arrendamento|-1146000
itr|S|DRE|P|2025-01-01|2025-06-30|3.01|Receita de Venda de Bens e/ou Serviços|37554000
itr|S|DRE|U|2026-01-01|2026-06-30|3.01|Receita de Venda de Bens e/ou Serviços|37813000
itr|S|DRE|P|2025-01-01|2025-06-30|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|1934000
itr|S|DRE|U|2026-01-01|2026-06-30|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|2704000
itr|S|DRE|P|2025-01-01|2025-06-30|3.11|Lucro/Prejuízo do Período|336000
itr|S|DRE|U|2026-01-01|2026-06-30|3.11|Lucro/Prejuízo do Período|804000
itr|S|DVA|P|2025-01-01|2025-06-30|7.04.01|Depreciação, Amortização e Exaustão|-866000
itr|S|DVA|U|2026-01-01|2026-06-30|7.04.01|Depreciação, Amortização e Exaustão|-927000
itr|S|DFC_MI|P|2025-01-01|2025-06-30|6.01.01.04|Depreciação e Amortização|866000
itr|S|DFC_MI|U|2026-01-01|2026-06-30|6.01.01.04|Depreciação e Amortização|927000
itr|S|DFC_MI|P|2025-01-01|2025-06-30|6.03.09|Pagamento de Passivo de Arrendamento|-161000
itr|S|DFC_MI|U|2026-01-01|2026-06-30|6.03.09|Pagamento de Passivo de Arrendamento|-165000
itr|S|DFC_MI|P|2025-01-01|2025-06-30|6.03.10|Pagamento de Juros de Passivo de Arrendamento|-566000
itr|S|DFC_MI|U|2026-01-01|2026-06-30|6.03.10|Pagamento de Juros de Passivo de Arrendamento|-641000
itr|S|BPA|U||2026-06-30|1.01.01|Caixa e Equivalentes de Caixa|4473000
itr|S|BPA|U||2026-06-30|1.01.02|Aplicações Financeiras|0
itr|S|BPP|U||2026-06-30|2.01.04|Empréstimos e Financiamentos|2176000
itr|S|BPP|U||2026-06-30|2.01.04.03|Financiamento por Arrendamento|0
itr|S|BPP|U||2026-06-30|2.01.05.02.17|Passivo de Arrendamento|511000
itr|S|BPP|U||2026-06-30|2.02.01|Empréstimos e Financiamentos|14106000
itr|S|BPP|U||2026-06-30|2.02.02.02.09|Passivo de Arrendamento|10200000
itr|S|BPP|U||2026-06-30|2.03|Patrimônio Líquido|6346000
dfp|G|DRE|U|2025-01-01|2025-12-31|3.01|Receita de Venda de Bens e/ou Serviços|10497046
dfp|G|DRE|U|2025-01-01|2025-12-31|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|2375728
dfp|G|DRE|U|2025-01-01|2025-12-31|3.11|Lucro/Prejuízo Consolidado do Período|1475168
dfp|G|DRE|U|2025-01-01|2025-12-31|3.11.01|Atribuído a Sócios da Empresa Controladora|0
dfp|G|DRE|U|2025-01-01|2025-12-31|3.11.02|Atribuído a Sócios Não Controladores|0
dfp|G|DRE|U|2025-01-01|2025-12-31|3.04.04|Outras Receitas Operacionais|1400000
dfp|G|DVA|U|2025-01-01|2025-12-31|7.04.01|Depreciação, Amortização e Exaustão|-758497
dfp|G|DFC_MI|U|2025-01-01|2025-12-31|6.01.01.04|Depreciação e amortização|491475
dfp|G|DFC_MI|U|2025-01-01|2025-12-31|6.01.01.19|Depreciação sobre direito de uso|270673
dfp|G|DFC_MI|U|2025-01-01|2025-12-31|6.03.15|Amortização do passivo de arrendamento|-372227
itr|G|DRE|P|2025-01-01|2025-06-30|3.01|Receita de Venda de Bens e/ou Serviços|4840357
itr|G|DRE|U|2026-01-01|2026-06-30|3.01|Receita de Venda de Bens e/ou Serviços|5013675
itr|G|DRE|P|2025-01-01|2025-06-30|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|327703
itr|G|DRE|U|2026-01-01|2026-06-30|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|326364
itr|G|DRE|P|2025-01-01|2025-06-30|3.11|Lucro/Prejuízo Consolidado do Período|116560
itr|G|DRE|U|2026-01-01|2026-06-30|3.11|Lucro/Prejuízo Consolidado do Período|172958
itr|G|DVA|P|2025-01-01|2025-06-30|7.04.01|Depreciação, Amortização e Exaustão|-356362
itr|G|DVA|U|2026-01-01|2026-06-30|7.04.01|Depreciação, Amortização e Exaustão|-401991
itr|G|DFC_MI|P|2025-01-01|2025-06-30|6.01.01.04|Depreciação e amortização|228430
itr|G|DFC_MI|U|2026-01-01|2026-06-30|6.01.01.04|Depreciação e amortização|264525
itr|G|DFC_MI|P|2025-01-01|2025-06-30|6.01.01.19|Depreciação sobre direito de uso|128548
itr|G|DFC_MI|U|2026-01-01|2026-06-30|6.01.01.19|Depreciação sobre direito de uso|137686
itr|G|DFC_MI|P|2025-01-01|2025-06-30|6.03.15|Amortização do passivo de arrendamento|-176927
itr|G|DFC_MI|U|2026-01-01|2026-06-30|6.03.15|Amortização do passivo de arrendamento|-194281
itr|G|BPA|U||2026-06-30|1.01.01|Caixa e Equivalentes de Caixa|918437
itr|G|BPA|U||2026-06-30|1.01.02|Aplicações Financeiras|218014
itr|G|BPP|U||2026-06-30|2.01.04|Empréstimos e Financiamentos|672655
itr|G|BPP|U||2026-06-30|2.01.04.03|Financiamento por Arrendamento|0
itr|G|BPP|U||2026-06-30|2.01.04.03.01|Certificados de recebíveis|0
itr|G|BPP|U||2026-06-30|2.01.05.02.11|Passivo de arrendamento|260166
itr|G|BPP|U||2026-06-30|2.02.01|Empréstimos e Financiamentos|1759518
itr|G|BPP|U||2026-06-30|2.02.02.02.06|Passivo de arrendamento|981126
itr|G|BPP|U||2026-06-30|2.02.02.02.07|Arrendamento a receber de franqueados|55555
itr|G|BPP|U||2026-06-30|2.03|Patrimônio Líquido Consolidado|5403029
itr|G|BPP|U||2026-06-30|2.03.09|Participação dos Acionistas Não Controladores|0
dfp|V|DRE|U|2025-01-01|2025-12-31|3.01|Receita de Venda de Bens e/ou Serviços|3026581564
dfp|V|DRE|U|2025-01-01|2025-12-31|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|726321236
dfp|V|DRE|U|2025-01-01|2025-12-31|3.11|Lucro/Prejuízo Consolidado do Período|619502301
dfp|V|DVA|U|2025-01-01|2025-12-31|7.04.01|Depreciação, Amortização e Exaustão|-152835915
dfp|V|DFC_MI|U|2025-01-01|2025-12-31|6.01.01.02|Depreciação e amortização|162858011
dfp|V|DFC_MI|U|2025-01-01|2025-12-31|6.03.07|Amortização de arrendamentos direito de uso|-101166335
itr|V|DRE|P|2025-01-01|2025-06-30|3.01|Receita de Venda de Bens e/ou Serviços|1100912502
itr|V|DRE|U|2026-01-01|2026-06-30|3.01|Receita de Venda de Bens e/ou Serviços|1428643410
itr|V|DRE|P|2025-01-01|2025-06-30|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|265245818
itr|V|DRE|U|2026-01-01|2026-06-30|3.05|Resultado Antes do Resultado Financeiro e dos Tributos|290226944
itr|V|DRE|P|2025-01-01|2025-06-30|3.11|Lucro/Prejuízo Consolidado do Período|246770680
itr|V|DRE|U|2026-01-01|2026-06-30|3.11|Lucro/Prejuízo Consolidado do Período|232461251
itr|V|DVA|P|2025-01-01|2025-06-30|7.04.01|Depreciação, Amortização e Exaustão|-76874841
itr|V|DVA|U|2026-01-01|2026-06-30|7.04.01|Depreciação, Amortização e Exaustão|-78138369
itr|V|DFC_MI|P|2025-01-01|2025-06-30|6.01.01.02|Depreciação e amortização|81645251
itr|V|DFC_MI|U|2026-01-01|2026-06-30|6.01.01.02|Depreciação e amortização|83561582
itr|V|DFC_MI|P|2025-01-01|2025-06-30|6.03.07|Amortização de arrendamentos direito de uso|-53200226
itr|V|DFC_MI|U|2026-01-01|2026-06-30|6.03.07|Amortização de arrendamentos direito de uso|-33878303
itr|V|BPA|U||2026-06-30|1.01.01|Caixa e Equivalentes de Caixa|416659228
itr|V|BPA|U||2026-06-30|1.01.02|Aplicações Financeiras|0
itr|V|BPP|U||2026-06-30|2.01.04|Empréstimos e Financiamentos|219846622
itr|V|BPP|U||2026-06-30|2.01.05.02.04|Arrendamentos a pagar|15241383
itr|V|BPP|U||2026-06-30|2.01.05.02.05|Arrendamentos de direito de uso a pagar|83722353
itr|V|BPP|U||2026-06-30|2.02.01|Empréstimos e Financiamentos|298484700
itr|V|BPP|U||2026-06-30|2.02.02.02.04|Arrendamentos de direito de uso a pagar|608465095
itr|V|BPP|U||2026-06-30|2.03|Patrimônio Líquido Consolidado|3184286048
itr|V|BPP|U||2026-06-30|2.03.09|Participação dos Acionistas Não Controladores|0
"""

CAPITAL = {
    # doc: [(empresa, dt_refer, ON, PN, ON tesouraria, PN tesouraria)]
    "itr": [("M", "2026-06-30", 2302987204, 0, 705364, 0), ("S", "2026-06-30", 1353531, 0, 15091, 0),
            ("G", "2026-06-30", 502065599, 0, 2560, 0), ("V", "2026-06-30", 236197769, 0, 1062717, 0)],
    "dfp": [("M", "2025-12-31", 2248469834, 0, 3644947, 0), ("S", "2025-12-31", 1353497, 0, 11789, 0),
            ("G", "2025-12-31", 500058238, 0, 2560, 0), ("V", "2025-12-31", 236197769, 0, 1125955, 0)],
}
TICKERS = {"M": "GMAT3", "S": "ASAI3", "G": "RIAA3", "V": "VIVA3"}   # Guararapes: GUAR3 virou RIAA3 em 2026
SECTOR = {"M": ("Comércio (Atacado e Varejo)", "Supermercados e atacarejo"),
          "S": ("Comércio (Atacado e Varejo)", "Atacarejo (Comércio Atacadista)"),
          "G": ("Comércio (Atacado e Varejo)", "Loja de Departamentos (Comércio Varejista)"),
          "V": ("Comércio (Atacado e Varejo)", "Joalheria (Comércio Varejista)")}

GRUPO = {"DRE": "Demonstração do Resultado", "BPA": "Balanço Patrimonial Ativo", "BPP": "Balanço Patrimonial Passivo",
         "DVA": "Demonstração de Valor Adicionado", "DFC_MI": "Demonstração do Fluxo de Caixa (Método Indireto)"}
FLOW_HEAD = "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA"
BAL_HEAD = "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA"
DOC_REFER = {"dfp": "2025-12-31", "itr": "2026-06-30"}
DOC_YEAR = {"dfp": 2025, "itr": 2026}


def _enc(text: str) -> bytes:
    return text.encode("latin-1")


def build(data_dir: Path) -> Path:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, list[str]]] = {"dfp": {}, "itr": {}}

    for line in DATA.strip().splitlines():
        doc, co, stmt, ordem, ini, fim, code, desc, val = line.split("|")
        cnpj, name, cd = COS[co]
        suffix = "ind" if co in IND_ONLY else "con"
        grupo = f"DF {'Individual' if suffix == 'ind' else 'Consolidado'} - {GRUPO[stmt]}"
        ordem_txt = "ÚLTIMO" if ordem == "U" else "PENÚLTIMO"
        common = [cnpj, DOC_REFER[doc], "1", name, cd, grupo, "REAL", ESC[co], ordem_txt]
        cols = common + ([ini, fim] if stmt not in ("BPA", "BPP") else [fim]) + [code, desc, f"{val}.0000000000", "S"]
        files[doc].setdefault(f"{stmt}_{suffix}", []).append(";".join(cols))

    # Armadilha: uma versão 1 antiga do ITR da Vivara com receita errada (deve ser ignorada pela v2)
    cnpj, name, cd = COS["V"]
    files["itr"]["DRE_con"].append(";".join([cnpj, "2026-06-30", "0", name, cd, "DF Consolidado - Demonstração do Resultado",
                                             "REAL", "UNIDADE", "ÚLTIMO", "2026-01-01", "2026-06-30", "3.01",
                                             "Receita de Venda de Bens e/ou Serviços", "1.0000000000", "S"]))

    for doc in ("dfp", "itr"):
        year = DOC_YEAR[doc]
        zpath = data_dir / f"{doc}_cia_aberta_{year}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for stmt in GRUPO:
                for suffix in ("con", "ind"):
                    head = BAL_HEAD if stmt in ("BPA", "BPP") else FLOW_HEAD
                    body = files[doc].get(f"{stmt}_{suffix}", [])
                    zf.writestr(f"{doc}_cia_aberta_{stmt}_{suffix}_{year}.csv", _enc("\n".join([head] + body) + "\n"))
            idx = ["CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC"]
            for co, (cnpj, name, cd) in COS.items():
                idx.append(f"{cnpj};{DOC_REFER[doc]};1;{name};{cd};{doc.upper()};1{cd};2026-08-06;"
                           f"http://www.rad.cvm.gov.br/ENETCONSULTA/frmDownloadDocumento.aspx?CodigoInstituicao=1&NumeroSequencialDocumento=1{cd}")
            zf.writestr(f"{doc}_cia_aberta_{year}.csv", _enc("\n".join(idx) + "\n"))
            cap = ["CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;QT_ACAO_ORDIN_CAP_INTEGR;QT_ACAO_PREF_CAP_INTEGR;QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_ORDIN_TESOURO;QT_ACAO_PREF_TESOURO;QT_ACAO_TOTAL_TESOURO"]
            for co, dt, on, pn, ton, tpn in CAPITAL[doc]:
                cnpj, name, _ = COS[co]
                cap.append(f"{cnpj};{dt};1;{name};{on};{pn};{on + pn};{ton};{tpn};{ton + tpn}")
            zf.writestr(f"{doc}_cia_aberta_composicao_capital_{year}.csv", _enc("\n".join(cap) + "\n"))

    geral_head = ("CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Empresarial;Data_Nome_Empresarial;"
                  "Nome_Empresarial_Anterior;Data_Constituicao;Codigo_CVM;Data_Registro_CVM;Categoria_Registro_CVM;"
                  "Data_Categoria_Registro_CVM;Situacao_Registro_CVM;Data_Situacao_Registro_CVM;Pais_Origem;"
                  "Pais_Custodia_Valores_Mobiliarios;Setor_Atividade;Descricao_Atividade;Situacao_Emissor;"
                  "Data_Situacao_Emissor;Especie_Controle_Acionario;Data_Especie_Controle_Acionario;"
                  "Dia_Encerramento_Exercicio_Social;Mes_Encerramento_Exercicio_Social;Data_Alteracao_Exercicio_Social;Pagina_Web")
    vm_head = ("CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Empresarial;Valor_Mobiliario;"
               "Sigla_Classe_Acao_Preferencial;Classe_Acao_Preferencial;Codigo_Negociacao;Composicao_BDR_Unit;Mercado;"
               "Sigla_Entidade_Administradora;Entidade_Administradora;Data_Inicio_Negociacao;Data_Fim_Negociacao;"
               "Segmento;Data_Inicio_Listagem;Data_Fim_Listagem")
    geral, vm = [geral_head], [vm_head]
    for co, (cnpj, name, cd) in COS.items():
        sec, act = SECTOR[co]
        geral.append(f"{cnpj};2026-01-01;1;1;{name};;;2000-01-01;{cd};2000-01-01;Categoria A;2010-01-01;Ativo;2000-01-01;"
                     f"Brasil;Brasil;{sec};{act};Fase Operacional;2000-01-01;Privado;2000-01-01;31;12;;http://ri.exemplo.com.br/")
        # Vivara: data fim == data início (erro de cadastro real, como o da C&A) -> continua negociando
        fim = "2020-01-01" if co == "V" else ""
        vm.append(f"{cnpj};2026-01-01;1;1;{name};Ações Ordinárias;;;{TICKERS[co]};;Bolsa;B3;B3 S.A. - Brasil, Bolsa, Balcão.;"
                  f"2020-01-01;{fim};Novo Mercado;2020-01-01;")
    # Caso real da Marisa: o FCA traz "022055" no lugar do ticker (corrigido em comps/ticker_fixes.csv);
    # e uma empresa com "N/A" sem correção, que não pode aparecer na lista
    for cnpj, name, code in (("61.189.288/0001-89", "MARISA LOJAS S.A.", "022055"),
                             ("99.999.999/0001-99", "SEM TICKER S.A.", "N/A")):
        geral.append(f"{cnpj};2026-01-01;1;1;{name};;;2000-01-01;99999;2000-01-01;Categoria A;2010-01-01;Ativo;2000-01-01;"
                     f"Brasil;Brasil;{SECTOR['G'][0]};Loja de Departamentos;Fase Operacional;2000-01-01;Privado;2000-01-01;31;12;;")
        vm.append(f"{cnpj};2026-01-01;1;1;{name};Ações Ordinárias;;;{code};;Bolsa;B3;B3;2010-06-14;;Novo Mercado;2010-06-14;")
    # Ticker antigo já encerrado: não pode ser usado
    vm.append(f"{COS['M'][0]};2026-01-01;1;1;GRUPO MATEUS S.A.;Ações Ordinárias;;;GMAT9;;Bolsa;B3;B3;2019-01-01;2020-01-01;;;")
    with zipfile.ZipFile(data_dir / "fca_cia_aberta_2026.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("fca_cia_aberta_geral_2026.csv", _enc("\n".join(geral) + "\n"))
        zf.writestr("fca_cia_aberta_valor_mobiliario_2026.csv", _enc("\n".join(vm) + "\n"))
    # FCA do ano anterior, com o ticker antigo da Guararapes
    cnpj, name, cd = COS["G"]
    sec, act = SECTOR["G"]
    with zipfile.ZipFile(data_dir / "fca_cia_aberta_2025.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("fca_cia_aberta_geral_2025.csv", _enc("\n".join([
            geral_head,
            f"{cnpj};2025-01-01;1;1;{name};;;2000-01-01;{cd};2000-01-01;Categoria A;2010-01-01;Ativo;2000-01-01;"
            f"Brasil;Brasil;{sec};{act};Fase Operacional;2000-01-01;Privado;2000-01-01;31;12;;http://ri.exemplo.com.br/"]) + "\n"))
        zf.writestr("fca_cia_aberta_valor_mobiliario_2025.csv", _enc("\n".join([
            vm_head,
            f"{cnpj};2025-01-01;1;1;{name};Ações Ordinárias;;;GUAR3;;Bolsa;B3;B3;1973-05-14;;Básico;1973-05-14;"]) + "\n"))
    return data_dir


if __name__ == "__main__":
    import sys
    print(build(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixture_data")))
