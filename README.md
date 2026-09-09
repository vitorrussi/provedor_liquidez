# Provedor de Liquidez

Ferramenta para apoiar decisões de fornecimento de liquidez em pools da Uniswap v3: cálculo de
Impermanent Loss (IL), APR de taxas, volatilidade e simulação de faixas de liquidez concentrada
contra o histórico real de preço do pool.

Ver também [`docs/guia-provedor-de-liquidez-defi.md`](docs/guia-provedor-de-liquidez-defi.md) para
o contexto conceitual (o que é IL, liquidez concentrada, riscos de LP, etc).

## Arquitetura

- **backend/** — FastAPI (Python). Busca dados de pools no subgraph oficial da Uniswap v3 (via
  gateway do The Graph) e expõe endpoints REST com os indicadores já calculados. A key do Graph
  fica só no backend — o frontend nunca fala direto com o Graph.
- **frontend/** — React + TypeScript + Vite. Busca de pools, dashboard de indicadores, calculadora
  de IL e simulador de faixa.

O núcleo matemático (`backend/app/indicators.py`) é puro (sem I/O) e tem cobertura de testes
(`backend/tests/test_indicators.py`), incluindo um teste de convergência que verifica que o IL de
liquidez concentrada (v3) converge para a fórmula clássica de IL full-range (v2) quando a faixa
tende a [0, ∞).

## Pré-requisitos

- Python 3.10+ (o repo foi testado com 3.12 via [`uv`](https://docs.astral.sh/uv/))
- Node.js 18+ (testado com Node 24 via `nvm`)
- Uma API key gratuita do The Graph: crie uma conta em https://thegraph.com/studio/ e gere uma key
  em "API Keys" — o free tier cobre uso de desenvolvimento tranquilamente.

## Backend

```bash
cd backend
python3 -m venv .venv  # ou: uv venv --python 3.12 .venv
source .venv/bin/activate
pip install -r requirements.txt  # ou: uv pip install -r requirements.txt

cp .env.example .env
# edite .env e cole sua GRAPH_API_KEY

uvicorn app.main:app --reload --port 8000
```

Rodar os testes (não precisa de API key — são só matemática pura):

```bash
pytest
```

A API sobe em `http://localhost:8000`. Docs interativas em `http://localhost:8000/docs`.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Abre em `http://localhost:5173`. Por padrão aponta para o backend em `http://localhost:8000` — se
você rodar o backend em outra porta, crie `frontend/.env.local` com:

```
VITE_API_BASE_URL=http://localhost:SUA_PORTA
```

## Indicadores implementados

- **Impermanent Loss (v3)** — calculado a partir da curva real de liquidez concentrada (não é a
  fórmula v2 aplicada ingenuamente), com o equivalente full-range mostrado ao lado para comparação.
- **Multiplicador de concentração** — quanto uma faixa específica amplifica o retorno de taxas em
  relação a uma posição full-range.
- **APR de taxas** — full-range (do pool) e estimado por posição (escalado pelo multiplicador de
  concentração e pela fração histórica de tempo dentro da faixa).
- **Volatilidade anualizada** — desvio-padrão dos log-retornos diários, anualizado.
- **Simulador de faixa** — roda a faixa escolhida contra os preços horários históricos reais do
  pool: fração do tempo dentro da faixa, APR estimado da posição, IL no preço final e dias
  necessários de acúmulo de taxas para compensar o IL. É uma estimativa histórica, não um backtest
  de execução (ignora gas e liquidez concorrente de outros LPs).

## Próximos passos possíveis

- Múltiplas pools lado a lado para comparação.
- Persistir posições do usuário (entrada, faixa, valor) para acompanhar IL/fees ao longo do tempo.
- Alertas de "saiu da faixa".
- Suporte a outras chains (Arbitrum, Base, Optimism) — trocar `UNISWAP_V3_SUBGRAPH_ID` no `.env`.
