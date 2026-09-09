# CLAUDE.md

Notas para trabalhar neste projeto. Contexto de produto/conceitos de LP fica em
[`docs/guia-provedor-de-liquidez-defi.md`](docs/guia-provedor-de-liquidez-defi.md) — isto aqui é
sobre como mexer no código sem se machucar.

## O que é

Ferramenta de apoio a decisão para provedores de liquidez na Uniswap v3: calcula Impermanent Loss,
APR de taxas, volatilidade e simula faixas de liquidez concentrada contra o histórico real de preço
de um pool. Backend FastAPI (Python) + frontend React/TypeScript (Vite). Dados vêm do subgraph
oficial da Uniswap v3 via gateway do The Graph.

## Preferência do usuário: não derrubar o servidor de dev à toa

**Antes de editar código, rode `scripts/dev.sh status`.** Se os dois (backend/frontend) já
estiverem rodando, faça as alterações e **deixe rodando** — não pare e não reinicie por padrão. O
usuário quer ver as mudanças aparecerem sozinhas (hot reload) sem precisar religar manualmente. Se
estava tudo parado, não suba nada por conta própria; se você mesmo subiu pra testar, derrube nos
mesmos moldes de como encontrou.

Quando um restart de fato é necessário (e aí sim vale rodar `scripts/dev.sh restart`, restaurando o
estado depois se antes estivesse parado):
- Alterar `backend/requirements.txt` (nova dependência) — `uvicorn --reload` não reinstala pacotes.
- Alterar `frontend/package.json` / rodar `npm install` — idem para o Vite.
- Alterar `backend/.env` (uvicorn `--reload` não recarrega env vars).
- Mudar `backend/app/config.py` de um jeito que dependa de import-time state cacheado (`get_settings`
  usa `@lru_cache`).

Para o resto (a grande maioria dos casos: editar rotas, componentes React, `indicators.py`, CSS),
o hot reload do uvicorn e o HMR do Vite já pegam a mudança sozinhos — não precisa fazer nada.

## Rodando localmente

```bash
scripts/dev.sh start|stop|restart|status|logs
```

Ver `README.md` para detalhes. Pontos que já morderam antes:

- **Porta 8000 está permanentemente ocupada** nesta máquina por um container Docker
  (`docker-proxy`) não relacionado a este projeto. Por isso o padrão do backend é **8787**, não
  8000. Se aparecer um erro de CORS no browser que não faz sentido, a causa mais provável é o
  backend não ter conseguido subir na porta esperada e o fetch estar batendo em outro serviço sem
  CORS — confira `scripts/dev.sh status` e `curl localhost:8787/api/health` antes de desconfiar de
  CORS de verdade.
- **Python/Node do sistema são antigos demais** (Python 3.8, Node 12 — Ubuntu 20.04). O venv do
  backend foi criado com `uv venv --python 3.12 .venv` e o frontend precisa de Node 18+ via `nvm`
  (`scripts/dev.sh` já cuida disso sozinho chamando `nvm use lts/*`). Se for rodar comandos manuais
  fora do script, lembre de `source .venv/bin/activate` (backend) ou `nvm use --lts` (frontend)
  primeiro, senão vai bater em `SyntaxError`/`TypeError: 'type' object is not subscriptable`.
- Logs ficam em `.dev/backend.log` e `.dev/frontend.log` (gitignored).
- Precisa de uma `GRAPH_API_KEY` em `backend/.env` (copiar de `.env.example`) pra qualquer rota que
  toque em dados de pool. Sem ela, a API responde com um erro claro (não crasha).

## A pegadinha mais cara deste projeto: convenção de preço

A Uniswap expõe dois campos de preço recíprocos por pool: `token0Price` (token0 por token1) e
`token1Price` (token1 por token0, a convenção nativa da fórmula do whitepaper v3). **Este projeto
inteiro — histórico OHLC, campo exibido na UI, e as funções de IL/liquidez concentrada em
`backend/app/indicators.py` — usa a convenção `token0Price`.** Isso já causou um bug real (silencioso,
sem erro, resultado numericamente plausível mas com o sinal invertido) porque a fórmula do
whitepaper foi implementada primeiro na convenção errada e só bateu o olho quando testada contra
dados reais.

Antes de mexer em `indicators.py` ou em qualquer código que passe "preço" para essas funções:
leia o docstring do módulo primeiro. Se for adicionar uma função nova que lida com preço, valide
numericamente contra uma consulta real ao subgraph (não só com `tick=0`, que não pega esse tipo de
erro — foi exatamente esse ponto cego que deixou o bug passar da primeira vez). Tem um teste de
regressão em `backend/tests/test_indicators.py` (`test_token0_price_matches_live_subgraph_reference`)
travando um valor real capturado em 2026-09-09; se ele quebrar, é sinal de que a convenção mudou ou
o subgraph mudou de schema — investigue antes de "corrigir" o teste.

## Testes

```bash
cd backend && source .venv/bin/activate && pytest        # matemática pura, não precisa de API key
cd frontend && npx tsc --noEmit -p tsconfig.app.json      # type-check (não tem suíte de testes JS ainda)
```

Para mudanças de UI, prefira checar de verdade no navegador (claude-in-chrome) além do type-check —
já pegou bug de rótulo (preço mostrado com o par de tokens invertido) que o TypeScript não acusa.

## Rastreamento de uso do The Graph

`backend/app/usage_tracker.py` incrementa um contador local (`backend/data/graph_usage.json`,
gitignored) a cada chamada real ao gateway, exposto em `GET /api/graph-usage` e mostrado discreto
no canto inferior direito da UI. É só uma estimativa local (não vê uso feito por outros lugares com
a mesma key, e reseta por mês civil, que pode não bater com o ciclo de billing do Studio) — a fonte
de verdade é o dashboard em thegraph.com/studio/apikeys/, que exige carteira conectada e assinatura
de mensagem (não automatizável por aqui).

Além do contador agregado, `backend/app/request_log.py` grava uma linha JSON por requisição em
`backend/data/graph_requests.log` (JSONL, gitignored): timestamp, nome da operação (extraído do
texto da query GraphQL), variáveis, status e duração. Consultar via
`GET /api/graph-usage/log?limit=N`. Não é retroativo — só registra a partir de quando esse recurso
foi adicionado, então não precisa bater com o total do contador (que tem um offset histórico
seedado manualmente).

## Estrutura

```
backend/app/
  indicators.py       # matemática pura (IL, APR, volatilidade, replay de faixa) — sem I/O
  graph_client.py      # cliente HTTP fino pro gateway do The Graph (key nunca sai daqui)
  usage_tracker.py     # contador local de consultas
  services/pools.py    # queries GraphQL + mapeamento pros schemas
  routers/              # rotas FastAPI
  schemas.py            # modelos Pydantic (request/response)
  config.py             # settings via pydantic-settings (.env)

frontend/src/
  api/client.ts         # wrapper fetch tipado pro backend
  components/           # um componente por seção do dashboard
  format.ts              # helpers de formatação (USD, %, preço, data)
```
