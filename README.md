# Comps automáticos a partir da CVM

Digite o ticker de uma empresa e receba, em menos de um minuto:

1. **Excel de trading comps** no padrão de banco: múltiplos com fórmulas vivas, média, mediana, valuation implícito e uma aba de **auditoria** dizendo de qual documento e de qual conta da CVM saiu cada número.
2. **One-pager em PowerPoint** da empresa-alvo: descrição do negócio, desempenho da ação, indicadores, resumo financeiro e posicionamento vs. peers (gráficos nativos, editáveis).

Tudo a partir de **dados públicos**: Portal de Dados Abertos da CVM (DFP + ITR + Formulário Cadastral) e cotações do Yahoo Finance.

3. **Valuation por teses (DCF + football field):** você escreve as teses de investimento; a IA as traduz em premissas (crescimento, margem, capex, capital de giro) para três cenários, com justificativa; você revisa; o código valida, calcula o DCF e monta o football field comparando DCF, comps e a faixa de preço de 12 meses.

## Como rodar no Windows

1. Instale o Python 3.12 ou 3.13 em [python.org/downloads](https://www.python.org/downloads/) e marque **"Add python.exe to PATH"** no instalador.
2. Extraia o zip e dê dois cliques em **`iniciar.bat`**. Na primeira vez ele cria o ambiente, instala as dependências (alguns minutos), roda os testes e abre o app no navegador.
3. Para usar a IA, abra o arquivo `.env` no Bloco de Notas e cole sua chave em `ANTHROPIC_API_KEY=`.

Pelo PowerShell, o equivalente é:

```powershell
py -m venv .venv
.venv\Scripts\activate          # se der erro de permissão: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
python -m pytest -q
python -m streamlit run app.py
```

## Publicar na nuvem (Streamlit Community Cloud, grátis)

Assim o app fica num link (ex.: `https://comps-valuation.streamlit.app`) e abre de qualquer computador, sem o seu PC ligado.

1. Crie um repositório no GitHub e suba o conteúdo desta pasta. **Não suba o arquivo `.env`**: ele tem a sua chave.
2. Em [share.streamlit.io](https://share.streamlit.io), entre com o GitHub, clique em **Create app** e escolha o repositório, a branch `main` e o arquivo `app.py`.
3. Em **Advanced settings**, escolha Python 3.12 e cole os segredos:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   APP_PASSWORD = "uma-senha"      # opcional: pede senha antes de abrir o app
   ```
4. Clique em **Deploy**. A primeira abertura baixa os dados da CVM (1 a 2 minutos).

Na nuvem os arquivos da CVM ficam em cache enquanto o app estiver acordado. Apps sem acesso por alguns dias "dormem" e acordam no primeiro clique. O Yahoo às vezes limita acessos vindos de servidores na nuvem; nesse caso o app avisa e a empresa fica de fora.

## Como rodar (Linux/Mac)

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # coloque sua ANTHROPIC_API_KEY (opcional)

python -m pytest -q                                    # 7 testes com números reais da CVM
python3 cli.py LREN3 --peers CEAB3 RIAA3 AZZA3 VIVA3 --check   # só imprime a tabela
python3 cli.py LREN3 --peers CEAB3 RIAA3 AZZA3 VIVA3 --dcf --tese "A margem volta a subir com a nova logística"
streamlit run app.py                                   # interface web (aba "Valuation por teses")
```

O primeiro uso baixa ~60 MB da CVM para `data/` (cache local, reaproveitado depois).
Sem chave da Anthropic, tudo funciona; a sugestão de peers usa o setor da CVM e a descrição usa o texto cadastral.

## Arquitetura

```
CVM dados abertos ──► cvm.py ──► financials.py ──┐
  (DFP, ITR, FCA)     download     LTM, EBITDA,  │
                      + cache      dívida, IFRS16 ├─► engine.py ──► excel.py    (comps .xlsx)
Yahoo Finance ──────► market.py ─────────────────┘   múltiplos  └─► onepager.py (one-pager .pptx)
                      preço, valor de mercado         estatística
Claude (Anthropic) ─► ai.py: escolhe peers de uma lista fechada da CVM + escreve a descrição
```

| Módulo | Responsabilidade |
|---|---|
| `comps/cvm.py` | Baixa e lê os zips da CVM (latin-1, `;`), cache com validade por tipo de arquivo |
| `comps/universe.py` | Ticker ↔ CNPJ, nome, setor e atividade (Formulário Cadastral) |
| `comps/financials.py` | Extrai e calcula os fundamentos, guardando a trilha de auditoria |
| `comps/market.py` | Cotações (Yahoo, com cache e preço manual de contingência) e valor de mercado por classe de ação |
| `comps/engine.py` | Monta a tabela de comps, estatísticas dos peers e valuation implícito |
| `comps/excel.py` / `comps/onepager.py` | Saídas no padrão de IB |
| `comps/ui.py` | Tema escuro e blocos visuais do app (tabela comparativa, cartões, sparklines), testáveis sem o Streamlit |
| `comps/ai.py` | Camada de IA com travas (ver abaixo) |

## Decisões de metodologia

- **LTM** = último ano fechado (DFP) + acumulado do ano no último ITR − mesmo acumulado do ano anterior. O ITR traz as colunas "ÚLTIMO" e "PENÚLTIMO", então tudo vem do mesmo documento.
- **EBITDA** = EBIT (conta 3.05) + D&A. A D&A vem das linhas de depreciação/amortização do DFC (o EBITDA não é uma conta padronizada da CVM). Testei a regra nas 384 empresas não financeiras do ITR 2T26: em 90% ela bate com a DVA dentro de 15%; nas divergências, o DFC costuma estar certo (ex.: a DVA de algumas empresas exclui a depreciação do direito de uso).
- **IFRS 16**: o arrendamento aparece ora dentro de "Empréstimos e Financiamentos" (ex.: Grupo Mateus), ora em "Outros" (ex.: Guararapes, Magalu). O código identifica e separa os dois casos, evitando dupla contagem. O EV padrão inclui arrendamentos (consistente com EBITDA pós-IFRS 16); a versão **ex-IFRS16** tira arrendamentos do EV e subtrai os pagamentos de arrendamento do EBITDA, como o mercado costuma olhar varejo.
- **Consolidado × individual**: empresas sem controladas (ex.: Assaí) só publicam o individual; o código detecta e usa a base disponível.
- **Escala das ações**: a CVM publica a quantidade de ações às vezes em unidades (Mateus: 2,3 bilhões) e às vezes em milhares (Renner: 1,0 milhão), sem indicar. A escala é resolvida comparando com o nº de ações do Yahoo ou pela plausibilidade do P/VPA.
- **Valores em UNIDADE × MIL**: respeita a coluna `ESCALA_MOEDA` (ex.: Vivara reporta em reais, não em milhares).
- **Reapresentações**: usa sempre a versão mais recente de cada documento.
- **Cadastro de tickers**: um código antigo continua encontrando a empresa, mas a cotação usa o código atual (ex.: a Guararapes passou de GUAR3 para RIAA3 no FCA de 2026). Papéis com "data fim de negociação" igual à data de início são tratados como erro de cadastro e seguem válidos (caso real da C&A, CEAB3). O código de negociação é texto livre no FCA: só vale o que tem formato de ticker da B3. Cerca de 30 empresas preenchem outra coisa (a Marisa informa "022055" em vez de AMAR3; a CSN, "4030"). As correções conhecidas ficam em `comps/ticker_fixes.csv`, e o usuário pode acrescentar as suas em `data/tickers_manuais.csv`. Empresa sem ticker válido não aparece na busca.

## Valuation por teses (DCF)

| Etapa | Quem faz | Detalhe |
|---|---|---|
| Teses | Analista (a IA pode sugerir pontos de partida) | Uma frase por tese, sem números |
| Premissas | IA propõe, código valida, analista aprova | Crescimento e margem EBITDA ex-IFRS16 por ano, capex/receita, capital de giro/receita; cada premissa cita as teses que a justificam. Limites: crescimento entre −30% e +50%, margem até 15 p.p. da histórica |
| FCFF | Código | EBITDA ex-IFRS16 − IR sobre o EBIT − capex − variação do capital de giro, 5 anos |
| WACC | Código | CAPM em reais: taxa livre de risco (média da Selic esperada no Focus 2026–2029) + beta (regressão semanal de 2 anos contra o Ibovespa, ajuste de Blume) × prêmio de risco (Damodaran) |
| Valor terminal | Código | Gordon: FCFF do ano 5 × (1 + g) / (WACC − g); g = inflação de longo prazo + ~1% real |
| Football field | Código | Comps (P25–P75 de EV/EBITDA e P/L), DCF (pessimista a otimista) e faixa de preço de 12 meses |

Convenção **ex-IFRS 16**: o aluguel é tratado como despesa (sai do EBITDA), então a dívida de arrendamento não entra na ponte EV → equity. O Excel do modelo tem as abas Football field, Teses, Premissas, WACC, DCF (3 cenários), Sensibilidade (WACC × g) e Histórico, tudo com fórmulas.

## A IA e por que números nunca passam por ela

O Claude faz só três coisas:
1. **Sugerir peers**, escolhendo de uma lista fechada de empresas listadas do mesmo setor na CVM. O que vier fora da lista é descartado, então o modelo não consegue inventar empresa.
2. **Escrever a descrição do negócio.** Se escapar algum número no texto, o bullet é descartado: os números do slide vêm só do código auditável.
3. **Traduzir teses em premissas do DCF.** Premissa é entrada, não resultado: a IA propõe, o código trava valores fora de faixa (e avisa), o analista edita, e o cálculo é todo do código.

Em banco, um múltiplo errado destrói a credibilidade do material. Por isso a IA cuida de linguagem e julgamento qualitativo, e o código determinístico cuida dos números.

## Limitações conhecidas

- Não ajusta itens não recorrentes (o EBITDA é o contábil reportado).
- Dívida líquida não inclui derivativos nem aplicações de longo prazo.
- Não se aplica a bancos e seguradoras (layout de demonstrações diferente).
- Para companhias com várias classes negociadas (ON/PN/units), o valor de mercado soma classe por classe; units sem ON/PN negociadas usam o preço da unit como aproximação.
