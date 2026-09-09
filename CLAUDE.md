# CLAUDE.md

Notas para trabalhar neste projeto. Contexto de produto/conceitos de LP fica em
[`docs/guia-provedor-de-liquidez-defi.md`](docs/guia-provedor-de-liquidez-defi.md) — isto aqui é
sobre como mexer no código sem se machucar.

## O que é

Ferramenta de apoio a decisão para provedores de liquidez: calcula Impermanent Loss, APR de taxas,
volatilidade e simula faixas de liquidez concentrada contra o histórico real de preço de um pool.
Backend FastAPI (Python) + frontend React/TypeScript (Vite). Dados vêm dos subgraphs oficiais da
Uniswap v2, v3 e v4 (Ethereum mainnet) e de um subgraph comunitário do Aerodrome Slipstream (Base),
todos via gateway do The Graph (um subgraph por protocolo).

## TVL do subgraph pode estar errado -- por que existe verificação on-chain

O campo `totalValueLockedUSD`/`reserveUSD` do subgraph comunitário da Uniswap é calculado por
tracking incremental (soma/subtrai a cada mint/burn/collect) e **não resincroniza com o saldo real**
do contrato -- em pools com histórico de posições complexo isso diverge, às vezes muito (achado real:
pool `0xCBCdF9626bC03E24f779434178A73a0B4bad62eD`, WBTC/WETH 0,30%, subgraph reportava **$204M**,
saldo real (e o app oficial da Uniswap) mostravam **~$42M** -- quase 5x de diferença. Confirmei que
não era erro de preço: o `derivedETH` do WBTC bateu com um pool de referência independente
(WBTC/USDC), e o TVL do subgraph era matematicamente consistente com seus próprios
`totalValueLockedToken0`/`Token1` errados -- ou seja, o saldo rastreado é que está errado, não a
conta.

Por isso `get_pool_detail` (`services/pools.py`) faz uma verificação on-chain de verdade: dois
`eth_call` de `ERC20.balanceOf(endereço_do_pool)` via `onchain_client.py` (JSON-RPC cru, sem
web3.py, contra um RPC público sem API key -- `config.eth_rpc_url`), multiplicados pelo mesmo preço
que o subgraph usaria (`derivedETH * ethPriceUSD`, que se mostrou confiável). Se as duas chamadas
funcionarem, `PoolDetail.total_value_locked_usd` é sobrescrito com esse valor e
`tvl_verified_onchain=True`; se o RPC falhar (timeout, fora do ar), cai pro valor do subgraph mesmo,
com `tvl_verified_onchain=False` (o frontend mostra um badge diferenciando os dois casos, ver
`PoolOverview.tsx`). Como isso melhora o TVL usado em `total_value_locked_usd`, o APR calculado a
partir dele (`fee_apr_full_range`) também fica mais preciso -- não só o número exibido.

**Essa verificação só roda no detalhe do pool** (`get_pool_detail`), não na busca/lista nem em
`get_related_pools` -- fazer isso pra até 50+ pools de uma busca seria lento demais e martelaria o
RPC público. A lista continua ordenada/exibida com o TVL do subgraph (documentado como aproximação
em `pool-search__hint`); só quando você abre um pool específico é que o número é conferido de
verdade. v2 usa o mesmo mecanismo (`bundle.ethPrice`, sem "USD" no nome -- diferente de v3/v4 que
usam `bundle.ethPriceUSD`, confirmado por introspecção).

Se o RPC público (`ethereum-rpc.publicnode.com`) ficar instável, troque `ETH_RPC_URL` no `.env` por
um endpoint próprio (Infura/Alchemy free tier já bastam, é só 2 `eth_call` por carregamento de pool).

## Multi-protocolo: v2, v3 e v4

v3 e v4 têm schema de subgraph praticamente idêntico (mesma entidade `Pool`/`PoolDayData`, mesma
matemática de liquidez concentrada) — são tratados pelo mesmo código em `services/pools.py`,
parametrizado por `protocol` (só muda qual subgraph é consultado, ver `config.Settings.graph_gateway_url`
e `graph_client.run_query(..., protocol=...)`). v2 é um AMM de produto constante clássico (entidade
`Pair`/`PairDayData`, sem `feeTier`/tick/liquidez concentrada, taxa sempre fixa em 0,30%, sem
`feesUSD` indexado — estimado como `volumeUSD * 0.003`) e tem queries GraphQL próprias
(`_SEARCH_QUERY_V2`, `_BATCH_DAY_DATA_QUERY_V2`, `_POOL_DETAIL_QUERY_V2`).

IDs de pool expostos ao frontend levam um prefixo de protocolo, ex: `v2:0xabc...`, `v4:0xabc...`,
`aerodrome:0xabc...` (`_to_pool_summary`/`_split_pool_id` em `services/pools.py`) — sem isso não dá
pra saber em qual dos quatro subgraphs buscar o detalhe de um pool a partir só do endereço.
`client.ts` faz `encodeURIComponent` do id antes de montar a URL por causa do `:`.

v2 não tem histórico OHLC indexado (`PairDayData` só tem reservas/volume, sem open/high/low/close) e
não tem liquidez concentrada — por isso um pool v2 mostra uma versão simplificada no frontend: sem
`PriceChart`, sem `RangeSimulator`, e a `ImpermanentLossCalculator` esconde os inputs de faixa
(price_lower/price_upper) e usa só o IL clássico full-range (`impermanent_loss_v2` em
`indicators.py`, já existia antes desse recurso). `get_pool_day_data`/`get_pool_hour_data` lançam
`GraphQueryError` se chamados com um pool v2 — não deveria acontecer, já que o frontend não oferece
essas telas para v2, mas é o comportamento se algo chamar na mão.

O subgraph v4 foi observado respondendo em >20s pra termos de busca comuns (ex: "WETH") — bem mais
lento que v3. Por isso `search_pools()` isola cada protocolo com `asyncio.gather(..., return_exceptions=True)`
e usa um timeout mais curto (`_SEARCH_TIMEOUT = 10.0`) só pras buscas: se um protocolo falhar ou
estourar o timeout, os outros ainda aparecem em vez de derrubar a busca inteira. Isso é intencional,
não um bug — se notar resultados de v4 (ou Aerodrome) faltando ocasionalmente numa busca por termo
muito comum, é essa degradação graciosa agindo, não um erro silencioso. Com 4 protocolos em vez de 3,
uma busca completa (com enriquecimento de volume/APR) pode levar ~10-15s.

## Aerodrome Slipstream (Base)

Aerodrome Slipstream é um fork da Uniswap v3 que roda na **Base** (chain id 8453), não em Ethereum
mainnet — por isso é tratado como um quarto protocolo (`protocol="aerodrome"`), não como só mais uma
versão. Schema do subgraph é praticamente idêntico ao de v3/v4 (`Pool`/`PoolDayData`, `feeTier` em
vez de `tickSpacing` -- confirmado por introspecção real em 2026-09-09, apesar da Slipstream permitir
taxa por pool configurável via governança, os valores observados seguem a mesma convenção de
centésimos de bip da Uniswap), então reaproveita o mesmo código de `_get_pool_detail_v3v4`/
`_search_v3v4`/`_related_v3v4` que v3/v4 -- só muda qual subgraph é consultado.

**O subgraph usado (`GENunSHWLBXm59mBSgPzQ8metBEp9YDfdqwFr91Av1UM`, "Aerodrome Base Full") não é
publicado/mantido pela Aerodrome** -- é um subgraph comunitário de terceiros, sem SLA. Verificado em
2026-09-09: `hasIndexingErrors: false`, bloco recente, e o `factories.id` retornado bate com o
CLFactory real da Aerodrome on-chain (`0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a`, confirmado via
BaseScan) -- então é real e consistente, mas pode ficar desatualizado ou sair do ar sem aviso, já que
não tem o mesmo tipo de garantia dos subgraphs oficiais da Uniswap. Se ficar instável, troque
`AERODROME_SLIPSTREAM_SUBGRAPH_ID` no `.env` (outros candidatos encontrados no Graph Explorer na
época — `base-v3-aerodrome` e afins — estavam com indexação quebrada ou eram subgraphs de escopo
estreito demais, tipo só transações de usuário; não são substitutos diretos sem reavaliar).

**Chain diferente tem implicações que já morderam em outros pontos do código, não só na query
GraphQL:**
- A verificação de TVL on-chain (ver seção acima) usa `_rpc_url_for_protocol()` em
  `services/pools.py`, que escolhe `BASE_RPC_URL` para Aerodrome e `ETH_RPC_URL` para v2/v3/v4 --
  **nunca compartilham o mesmo RPC**. Chamar `balanceOf` num RPC da chain errada não dá erro, só
  devolve saldo zerado (o contrato simplesmente não existe lá), o que produziria um TVL de $0 com
  `tvl_verified_onchain=true` -- silenciosamente pior que o bug que essa verificação existe pra
  corrigir. Por isso `onchain_client.get_erc20_balance` não tem RPC default nenhum: `rpc_url` é
  sempre explícito no chamador, de propósito, pra esse tipo de engano não poder acontecer sem uma
  mudança visível no código.
- Links de contrato de token usam `explorerTokenUrl(address, protocol)` (`format.ts`) -- basescan.org
  para Aerodrome, etherscan.io para os demais. Endereço igual em duas chains é um contrato
  completamente diferente; nunca monte esse link sem levar o protocolo em conta.
- `get_related_pools` só cruza protocolos da mesma chain (`_PROTOCOL_CHAIN` em `services/pools.py`):
  um pool Aerodrome só mostra outras pools Aerodrome do mesmo par (outras fee tiers), nunca pools
  Uniswap mainnet -- os endereços de token nunca bateriam entre chains mesmo que tentasse (WETH tem
  endereço diferente em cada chain), então cruzar seria só gasto de quota à toa.
- A verificação on-chain revelou, num teste real, uma divergência grande entre o
  `totalValueLockedUSD` do subgraph Aerodrome e o saldo real (~$67M vs ~$10M num pool WETH/USDC) --
  o mesmo tipo de bug de tracking incremental documentado na seção acima para a Uniswap. Reforça que
  a verificação on-chain não é só teatro pra esse subgraph específico, é necessária de verdade.

## Indicadores 7d/30d, pools relacionadas e o sentinel de taxa dinâmica da v4

`PoolSummary`/`PoolDetail` carregam `volume_7d_usd`/`apr_pool_7d` além dos de 30d (mesma
`_aggregate_pool_stats`, que agora retorna um `PoolDayStats` com as duas janelas). Para v3/v4, o
endpoint `/api/pools/{id}/indicators` também calcula `fee_apr_full_range_7d`/`annualized_volatility_7d`
reaproveitando o mesmo `daily` (últimos 30 dias) já buscado — sem chamada extra ao gateway.

`GET /api/pools/{id}/related` (`services/pools.py::get_related_pools`) busca outras pools/pairs do
mesmo par de tokens nos protocolos da mesma chain (outras fee tiers em v3/v4, a versão v2/v3/v4 do
mesmo par, ou outras fee tiers/tick spacings em Aerodrome -- ver seção "Aerodrome Slipstream (Base)"
sobre por que não cruza chains), filtrando TVL < $1k (dust/pools esquecidas — o APR calculado sobre
um TVL desprezível vira um número sem sentido, tipo >1000000%) e limitando a 6 resultados por TVL.
Usa `token0: $addr`/`token1: $addr` (endereço direto, não a busca por símbolo de `_SEARCH_QUERY`) — a
ordem token0/token1 é canônica (endereço menor primeiro) em todo deployment Uniswap v3-like, então
não precisa inverter.

**v4 tem um valor sentinel pra `feeTier`**: `8388608` (`0x800000`) significa "taxa dinâmica, definida
por um hook" — não é uma taxa fixa de verdade. `formatFeeTier` (frontend) trata esse caso
especificamente (mostra "dinâmica" em vez de "838.86%", que é o que dava antes de eu notar isso ao
testar `/related` com dados reais). Se for adicionar mais lugares que mostram `fee_tier` cru, lembre
desse sentinel.

`formatPercent` também tem um teto (`>10000%` / `<-10000%`) pro mesmo motivo do filtro de TVL acima —
sem ele, um pool com TVL de poucos dólares e algum volume registrado produz um "APR" de milhares de
por cento, tecnicamente correto pela conta mas sem nenhum valor informativo.

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

## Preferência do usuário: commitar ao terminar uma feature/fix

**Neste projeto, ao terminar de implementar uma feature, corrigir um bug, ou qualquer unidade de
trabalho coerente (testada e funcionando), crie um commit git sem esperar o usuário pedir
explicitamente.** Isso substitui, só neste repositório, a regra padrão de só commitar quando pedido.

- Rode `git status`/`git diff` antes de commitar pra revisar o que está sendo incluído (igual você
  já faria pra qualquer commit) — não adicione arquivos que pareçam não relacionados ao trabalho
  feito sem entender por quê estão lá.
- Uma unidade de trabalho = um commit. Se o pedido do usuário naturalmente virou vários pedaços
  independentes (ex: uma correção de bug + uma feature nova depois, em sequência), prefira vários
  commits pequenos a um só gigante — mensagens de commit continuam curtas e no estilo do histórico
  existente (`git log --oneline` pra referência), focadas no "porquê", não numa lista de arquivos.
- Isso não muda as regras de segurança de git de sempre: nunca `push` sem o usuário pedir
  explicitamente, nunca `--force`/`--no-verify`/`--amend` sem pedido explícito, nunca commitar
  segredos (`.env`, credenciais) mesmo que peçam.
- Se o trabalho ficou pela metade, quebrado, ou não testado, não commite só por commitar — espere
  terminar essa unidade de trabalho primeiro.

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
  pages/PoolPage.tsx    # página de detalhe do pool (rota /pool/:id)
  format.ts              # helpers de formatação (USD, %, preço, data)
```

## Navegação (react-router-dom)

Duas rotas, definidas em `App.tsx` (que também é o layout compartilhado — header/footer/`UsageBadge`
ficam fora do `<Routes>`): `/` é a busca (`components/PoolSearch.tsx`, que já é a "página" — não tem
um `SearchPage.tsx` separado) e `/pool/:id` é o detalhe (`pages/PoolPage.tsx`). O `id` da rota é o id
prefixado por protocolo (`v3:0xabc...`) vindo de `PoolSummary.id`, sempre passado por
`encodeURIComponent` ao montar o link/navigate (por causa do `:`) e por `decodeURIComponent` ao ler
de volta em `useParams()`.

O termo de busca fica sincronizado com a URL (`/?q=termo`, via `useSearchParams` dentro do próprio
`PoolSearch`) — é assim que o botão voltar do navegador consegue restaurar a lista depois de abrir um
pool: `PoolSearch` desmonta ao navegar pra `/pool/:id` (perde o estado local), mas ao voltar pra `/`
o efeito que dispara a busca roda de novo a partir do `q` da URL. Isso custa uma busca nova ao Graph
a cada "voltar" (aceitável frente ao limite de 100k/mês) — ordenação de coluna e o toggle de "ocultar
sem volume" não são persistidos na URL, só o termo.

A página de pool usa mais largura que a busca (classe `.app--wide` em `App.css`, aplicada em `App.tsx`
via `useLocation().pathname.startsWith('/pool/')`) — é por isso que existe mais espaço lá pra
estatísticas em 4 colunas.
