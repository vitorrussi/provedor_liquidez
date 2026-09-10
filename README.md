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

- [conda](https://github.com/conda-forge/miniforge) (Miniforge) — gerencia Python e Node num único
  ambiente conda, definido em `environment.yml` (Python 3.12 + Node 24). Não precisa de `uv`, `nvm`
  nem Python/Node do sistema.
- Uma API key gratuita do The Graph: crie uma conta em https://thegraph.com/studio/ e gere uma key
  em "API Keys" — o free tier cobre uso de desenvolvimento tranquilamente.

## Rodando tudo com um comando

Depois de instalar as dependências (seções abaixo), dá pra subir/derrubar os dois servidores juntos:

```bash
scripts/dev.sh start     # sobe backend (porta 8787) + frontend (porta 5173) em background
scripts/dev.sh status
scripts/dev.sh logs      # tail dos dois logs (Ctrl-C só sai do tail, servidores continuam)
scripts/dev.sh stop
scripts/dev.sh restart
```

Logs ficam em `.dev/backend.log` e `.dev/frontend.log`. Note que a porta padrão do backend é
**8787**, não 8000 — nesta config a 8000 costuma estar ocupada por outro serviço local (ex: um
container Docker), e se o backend não conseguir subir nela, requisições do navegador batem em outro
processo sem CORS configurado, dando um erro de CORS enganoso no console.

Portas customizáveis via env var, se 8787/5173 estiverem ocupadas: `BACKEND_PORT=8888 FRONTEND_PORT=5174 scripts/dev.sh start`.

## Setup (uma vez)

```bash
conda env create -f environment.yml   # cria o ambiente `provedor-liquidez` (Python 3.12 + Node 24)
make setup                            # ou: make conda-env backend-install frontend-install
```

`make setup` cria o ambiente conda (se ainda não existir) e instala as dependências de
backend (`pip install -r requirements.txt`) e frontend (`npm install`) dentro dele.

## Backend

```bash
conda activate provedor-liquidez
cd backend

cp .env.example .env
# edite .env e cole sua GRAPH_API_KEY

uvicorn app.main:app --reload --port 8787
```

Rodar os testes (não precisa de API key — são só matemática pura):

```bash
make test   # ou: conda activate provedor-liquidez && cd backend && pytest
```

A API sobe em `http://localhost:8787`. Docs interativas em `http://localhost:8787/docs`.

## Frontend

```bash
conda activate provedor-liquidez
cd frontend
npm run dev
```

Abre em `http://localhost:5173`. Por padrão aponta para o backend em `http://localhost:8787` — se
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
