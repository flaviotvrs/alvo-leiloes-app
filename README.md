# Alvo Leilões

Ferramenta pessoal para triagem e análise de viabilidade financeira de imóveis em leilão da Caixa Econômica Federal.

Substitui o processo manual de abrir editais um a um, extrair dados e calcular margens em planilha.

---

## O que já está implementado

### Importador — Caixa Econômica Federal
- Lê a planilha CSV disponível no site da Caixa (formato latin-1, separador `;`)
- Persiste imóveis e dados do edital no banco de dados
- **Idempotente**: re-importar a mesma planilha não duplica registros
- Infere o tipo do imóvel (residencial / comercial / terreno) pela descrição

### Calculadora de viabilidade financeira
Dado um imóvel e um valor estimado de mercado, calcula:

| Item | Fonte |
|---|---|
| Emolumentos de cartório | Tabela TJMG 2026 (Tabela 4-2026, item 5-e), 24 faixas até R$ 3,7 M, Nota XVII acima |
| ITBI | Alíquota por município (BH/Contagem/Betim 3%, Sete Lagoas 2,5%, demais estimativa) |
| Comissão do leiloeiro | Informada no edital ou estimada em 5% |
| Dívidas assumidas | IPTU em débito + condomínio em débito |
| Custo de carregamento | (IPTU mensal + condomínio mensal) × meses |
| Custos pós-arremate | Advogado (imissão na posse), reforma, outros |
| Comissão do corretor (venda) | Padrão 5,5%, configurável |
| IR sobre ganho de capital | Alíquota progressiva; 15% para a maioria dos casos |

**Base do ganho de capital para IR:**
```
ganho = (mercado − comissão_corretor) − (arremate + emolumentos + ITBI + comissão_leiloeiro + reforma)
IR    = max(0, ganho) × 15%
```

**Margem:**
```
total_investido = arremate + comissão_leiloeiro + emolumentos + ITBI
                + dívidas + carregamento + advogado + reforma + outros
total_custos    = total_investido + comissão_corretor + IR
lucro_líquido   = mercado − total_custos
margem          = lucro_líquido / total_investido × 100
```

### Interface Streamlit

**Lista de imóveis** (`streamlit_app.py`)
- Tabela com todos os imóveis importados
- Filtros na sidebar: Cidade, Bairro, Tipo, Faixa de preço (min + max), Modalidade, Análises (todos / com análise / sem análise)
- Filtros persistem ao navegar entre páginas
- Coluna 📊 indica imóveis que já possuem análise salva
- Clique na linha + botão "Abrir análise →" navega para o detalhe

**Detalhe + calculadora** (`pages/Detalhe.py`)
- Acessível via URL: `http://localhost:8501/Detalhe?imovel_id=<id>` (favoritável)
- Exibe dados do edital (preço, avaliação, desconto, modalidade, link do edital original)
- Formulário de inputs: valor de mercado estimado, dívidas, carregamento, custos pós-arremate, parâmetros avançados
- Resultado: breakdown de custos, métricas de lucro e margem, veredito viável / não viável
- Análises salvas no banco e exibidas em histórico por imóvel
- Análises são privadas por usuário (configurável via `APP_USER_ID` no `.env`)

---

## Stack

- **Python 3.12+**
- **PostgreSQL 16** via Docker Compose
- **SQLAlchemy 2.0** (ORM com `mapped_column` e `DeclarativeBase`)
- **Alembic** para migrations
- **pandas + openpyxl** para leitura da planilha
- **Streamlit 1.61** para a interface

---

## Configuração

### 1. Banco de dados

```bash
docker compose up -d
```

### 2. Ambiente Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Variáveis de ambiente

Copie `.env.example` para `.env` e ajuste:

```env
DATABASE_URL=postgresql://radar:radar@localhost:5432/radar_leiloes
APP_USER_ID=seu_nome   # identifica o dono das análises salvas
```

### 4. Migrations

```bash
alembic upgrade head
```

### 5. Importar a planilha da Caixa

Baixe a planilha em [leiloes.caixa.gov.br](https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp) e importe:

```python
from app.importers.caixa import importar_planilha_caixa
from app.db import SessionLocal

with SessionLocal() as session:
    importados, ignorados = importar_planilha_caixa("planilha.csv", session)
    session.commit()
    print(f"{importados} importados, {ignorados} já existiam")
```

### 6. Rodar a interface

```bash
streamlit run streamlit_app.py
```

Acesse em `http://localhost:8501`.

---

## Estrutura do projeto

```
radar-leiloes/
├── streamlit_app.py          # Página principal: lista de imóveis
├── pages/
│   └── Detalhe.py            # Detalhe do imóvel + calculadora
├── app/
│   ├── models.py             # Modelos SQLAlchemy (Imovel, Edital, AnaliseFinanceira)
│   ├── db.py                 # Engine, SessionLocal, USER_ID
│   ├── calculators/
│   │   └── viabilidade.py    # Calculadora financeira
│   ├── importers/
│   │   └── caixa.py          # Importador da planilha Caixa
│   └── tables/
│       ├── emolumentos_mg.py # Tabela TJMG 2026 de emolumentos
│       └── itbi.py           # Alíquotas de ITBI por município
├── migrations/               # Migrations Alembic
├── tests/
│   ├── test_calculadora.py   # Testes da calculadora e tabelas
│   └── test_importador_caixa.py
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## Testes

```bash
pytest
```

---

## Design para agentes autônomos (pós-MVP)

A função `_coletar_inputs_manuais()` em `Detalhe.py` isola toda a coleta manual de inputs e retorna um dict padronizado com `fonte="manual"`. No futuro, agentes especializados (análise de PDF do edital, pesquisa de comparáveis, estimativa de reforma) poderão substituir essa função mantendo o mesmo contrato — sem alterar a calculadora nem o modelo de persistência. O campo `fonte_valor_mercado` em `AnaliseFinanceira` rastreia a origem de cada análise.
