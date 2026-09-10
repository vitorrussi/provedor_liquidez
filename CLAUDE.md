# CLAUDE.md

Notas para trabalhar neste projeto. Contexto de produto/conceitos de LP fica em
[`docs/guia-provedor-de-liquidez-defi.md`](docs/guia-provedor-de-liquidez-defi.md) — isto aqui é
sobre como mexer no código sem se machucar.

## O que é

Ferramenta de apoio a decisão para provedores de liquidez: calcula Impermanent Loss, APR de taxas,
volatilidade e simula faixas de liquidez concentrada contra o histórico real de preço de um pool.
Backend FastAPI (Python) + frontend React/TypeScript (Vite). Dados vêm dos subgraphs oficiais da
Uniswap v2, v3 e v4 (Ethereum mainnet) e de subgraphs comunitários do Aerodrome Slipstream (Base) e
da Uniswap v3 em Polygon e Avalanche, todos via gateway do The Graph (um subgraph por protocolo).

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
`aerodrome:0xabc...`, `polygon:0xabc...`, `avalanche:0xabc...` (`_to_pool_summary`/`_split_pool_id`
em `services/pools.py`) — sem isso não dá pra saber em qual dos seis subgraphs buscar o detalhe de
um pool a partir só do endereço. `client.ts` faz `encodeURIComponent` do id antes de montar a URL
por causa do `:`.

v2 não tem histórico OHLC indexado (`PairDayData` só tem reservas/volume, sem open/high/low/close) e
não tem liquidez concentrada — por isso um pool v2 mostra uma versão simplificada no frontend: sem
`PriceChart`, sem `RangeSimulator`, e a `ImpermanentLossCalculator` esconde os inputs de faixa
(price_lower/price_upper) e usa só o IL clássico full-range (`impermanent_loss_v2` em
`indicators.py`, já existia antes desse recurso). `get_pool_day_data`/`get_pool_hour_data` lançam
`GraphQueryError` se chamados com um pool v2 — não deveria acontecer, já que o frontend não oferece
essas telas para v2, mas é o comportamento se algo chamar na mão.

O subgraph v4 foi observado respondendo em >20s pra termos de busca comuns (ex: "WETH") — bem mais
lento que v3; o subgraph de Polygon tem o mesmo problema pra buscas de texto livre sem piso de TVL
(ver seção "Uniswap v3 em Polygon e Avalanche" abaixo). Por isso `search_pools()` isola cada protocolo
com `asyncio.gather(..., return_exceptions=True)` e usa um timeout mais curto (`_SEARCH_TIMEOUT = 10.0`)
só pras buscas: se um protocolo falhar ou estourar o timeout, os outros ainda aparecem em vez de
derrubar a busca inteira. Isso é intencional, não um bug — se notar resultados de v4, Aerodrome ou
Polygon faltando ocasionalmente numa busca por termo muito comum, é essa degradação graciosa agindo,
não um erro silencioso. Com 6 protocolos, uma busca completa (com enriquecimento de volume/APR) pode
levar ~10-15s.

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
  `services/pools.py`, que escolhe o RPC certo por chain via `_CHAIN_RPC_SETTING`
  (`ETH_RPC_URL`/`BASE_RPC_URL`/`POLYGON_RPC_URL`/`AVALANCHE_RPC_URL`) -- **nunca compartilham o
  mesmo RPC**. Chamar `balanceOf` num RPC da chain errada não dá erro, só devolve saldo zerado (o
  contrato simplesmente não existe lá), o que produziria um TVL de $0 com `tvl_verified_onchain=true`
  -- silenciosamente pior que o bug que essa verificação existe pra corrigir. Por isso
  `onchain_client.get_erc20_balance` não tem RPC default nenhum: `rpc_url` é sempre explícito no
  chamador, de propósito, pra esse tipo de engano não poder acontecer sem uma mudança visível no
  código. Ver seção "Uniswap v3 em Polygon e Avalanche" abaixo pra mais duas chains no mesmo padrão.
- Links de contrato de token usam `explorerTokenUrl(address, protocol)` (`format.ts`) -- um
  explorador por chain (etherscan.io, basescan.org, polygonscan.com, snowtrace.io). Endereço igual em
  duas chains é um contrato completamente diferente; nunca monte esse link sem levar o protocolo em
  conta.
- `get_related_pools` só cruza protocolos da mesma chain (`_PROTOCOL_CHAIN` em `services/pools.py`):
  um pool Aerodrome só mostra outras pools Aerodrome do mesmo par (outras fee tiers), nunca pools
  Uniswap mainnet -- os endereços de token nunca bateriam entre chains mesmo que tentasse (WETH tem
  endereço diferente em cada chain), então cruzar seria só gasto de quota à toa.
- A verificação on-chain revelou, num teste real, uma divergência grande entre o
  `totalValueLockedUSD` do subgraph Aerodrome e o saldo real (~$67M vs ~$10M num pool WETH/USDC) --
  o mesmo tipo de bug de tracking incremental documentado na seção acima para a Uniswap. Reforça que
  a verificação on-chain não é só teatro pra esse subgraph específico, é necessária de verdade.

## Uniswap v3 em Polygon e Avalanche

Dois protocolos a mais, cada um sua própria chain: `protocol="polygon"` (Polygon PoS) e
`protocol="avalanche"` (Avalanche C-Chain) -- ambos Uniswap v3 de verdade (não fork), mesmo schema de
subgraph que v3/v4/Aerodrome, então reaproveitam 100% do código `_v3v4`/`_search_v3v4`/
`_get_pool_detail_v3v4` etc. em `services/pools.py` -- só muda qual subgraph é consultado
(`config.py::graph_gateway_url`) e qual RPC é usado pra verificação on-chain
(`_rpc_url_for_protocol`/`_CHAIN_RPC_SETTING`). Nenhum dos dois subgraphs é publicado/mantido pela
Uniswap Labs no gateway (sem SLA, igual Aerodrome) -- **verificados individualmente em 2026-09-10**
antes de usar, mesmo processo já documentado pra Aerodrome:
- **Polygon** (`3hCPRGf4z88VC5rsBKU5AA9FBBq5nF3jbKJG7VZCbhjm`): `factories.id` bate com
  `0x1F98431c8aD98523631AE4a59f267346ea31F984`, o endereço determinístico (CREATE2) da Uniswap V3
  Factory usado na maioria das chains v3 -- confere com `factories.id` da v3 mainnet.
  `hasIndexingErrors: false`.
- **Avalanche** (`GVH9h9KZ9CqheUEL93qMbq7QwgoBu32QXQDPR6bev4Eo`): `factories.id` bate com
  `0x740b1c1de25031C31FF4fC9A62f554A55cdC1baD` -- endereço DIFERENTE do determinístico de cima (a
  Avalanche não recebeu o deploy nas mesmas condições), confirmado batendo com o contrato rotulado
  "Uniswap V3: Factory" no Snowtrace (não é coincidência de endereço). `hasIndexingErrors: false`.
- A verificação on-chain (mesmo mecanismo documentado acima) já pegou uma divergência real num pool
  Avalanche testado: subgraph reportava ~$3,5M de TVL, saldo on-chain real era ~$1,08M -- ~3,2x de
  diferença, mesmo tipo de bug de tracking incremental já visto em Uniswap mainnet e Aerodrome. Mais
  uma confirmação de que a verificação on-chain generaliza bem pra subgraphs comunitários novos, não
  é algo calibrado só pros dois primeiros.

**Achado real ao testar o candidato de Polygon**: antes de escolher o subgraph atual, um outro
candidato (`uniswap-v3-avalanche`, achado numa busca de texto) respondia normalmente pra queries sem
filtro mas devolvia `"Type Query has no field factories"` -- acabou sendo só um subgraph de eventos
de criação de pool (`poolCreated`/`feeAmountEnabled`), não o schema completo de analytics. Reforça a
prática já estabelecida neste projeto: nunca confiar num subgraph só pelo nome/popularidade sem uma
consulta real confirmando o schema e os dados.

**A busca de texto livre (`q=`) na Polygon é lenta/instável pro mesmo tipo de query que já degrada
graciosamente pra v4** -- confirmado em 2026-09-10: uma query sem `where` de TVL, ordenada por
`totalValueLockedUSD` (exatamente o formato de `_search_query_v3v4`), estourou `_SEARCH_TIMEOUT`
(10s) de forma repetível, enquanto a mesma consulta com um `where` de TVL (formato do crawl do
índice, `_INDEX_POOLS_QUERY`) respondeu em segundos. Já é coberto pela mesma degradação graciosa que
protege contra a lentidão da v4 (`return_exceptions=True`, isolamento por protocolo) -- só documentado
aqui pra não ser confundido com um bug nesse protocolo especificamente se notado de novo.
**Consequência contraintuitiva pro usuário**: é o oposto do que se esperaria de um filtro -- deixar
"TVL mínimo" vazio na busca principal tende a ESCONDER resultados de Polygon (a query sem `where`
estoura o timeout), enquanto preencher um piso de TVL tende a REVELAR mais resultados de Polygon (a
query fica rápida o bastante pra não estourar). Se um usuário reportar "Polygon não aparece nunca
nessa busca", a primeira pergunta é se ele tem algum piso de TVL configurado nos filtros avançados.

**Chains pedidas mas NÃO implementadas ainda** (avaliadas e descartadas por ora, não esquecidas):
BNB Chain/BSC (a presença da Uniswap lá é pequena -- PancakeSwap domina, e teria schema diferente,
precisaria de código próprio tipo o de v2) e Robinhood Chain (L2 sobre Arbitrum, mainnet desde
2026-07-01, Uniswap é parceiro de lançamento lá, ~$130M/dia de volume em ações tokenizadas por lá --
mas **verificado em 2026-09-10 no Graph Explorer que essa chain ainda nem aparece na lista de redes
indexadas pelo The Graph** -- não é "subgraph imaturo", é "não existe subgraph nenhum pra consultar
via gateway", já que toda a arquitetura deste app (`graph_client.py`, `config.py::graph_gateway_url`)
depende do gateway do The Graph. Ver seção "Ações tokenizadas (RWA)" abaixo pro contexto completo de
por que isso foi investigado). Se algum dia forem adicionadas, seguir o mesmo processo de verificação
(introspecção + `factories.id` contra o contrato on-chain real) antes de confiar nos dados, exatamente
como feito aqui.

## Ações tokenizadas (RWA) -- pesquisado, NÃO implementado (2026-09-10)

Usuário pediu suporte a pools de ações tokenizadas de grandes empresas americanas (Apple, Microsoft,
Amazon, Google, Tesla, "e mais se der"). Pesquisa extensa feita, decisão foi **não implementar por
enquanto** -- não é falta de esforço, é que não existe liquidez de verdade acessível pela arquitetura
deste app hoje. Documentado aqui pra não perder o trabalho e pra saber exatamente o que reavaliar
depois, em vez de repetir a pesquisa do zero numa sessão futura.

**Endereços verificados (Backed Finance / "xStocks"), todos Ethereum mainnet, todos com fonte
independente (CSV oficial `github.com/backed-fi/cow-xstocks-tokenlist`, 3 deles cruzados também no
Etherscan)**:

| Empresa | Symbol on-chain | Endereço |
|---|---|---|
| Apple | AAPLx | `0x9d275685dc284c8eb1c79f6aba7a63dc75ec890a` |
| Microsoft | MSFTx | `0x5621737f42dae558b81269fcb9e9e70c19aa6b35` |
| Amazon | AMZNx | `0x3557ba345b01efa20a1bddc61f573bfd87195081` |
| Alphabet/Google | GOOGLx | `0xe92f673ca36c5e2efd2de7628f815f84807e803f` |
| Tesla | TSLAx | `0x8ad3c73f833d3f9a523ab01476625f269aeb7cf0` |
| Nvidia | NVDAx | `0xc845b2894dbddd03858fd2d643b4ef725fe0849d` |
| Meta | METAx | `0x96702be57cd9777f835117a809c7124fe4ec989a` |
| Netflix | NFLXx | `0xa6a65ac27e76cd53cb790473e4345c46e5ebf961` |
| Coinbase | COINx | `0x364f210f430ec2448fc68a49203040f6124096f0` |
| Broadcom | AVGOx | `0x38bac69cbbd28156796e4163b2b6dcb81e336565` |
| Visa | Vx | `0x2363fd1235c1b6d3a5088ddf8df3a0b3a30c5293` |
| JPMorgan | JPMx | `0xd9fc3e075d45254a1d834fea18af8041207dea0a` |
| Walmart | WMTx | `0x7aefc9965699fbea943e03264d96e50cd4a97b21` |
| Berkshire Hathaway B | BRK.Bx | `0x12992613fdd35abe95dec5a4964331b1ee23b50d` |

**Achado real (verificado com consulta direta ao subgraph, não suposição)**: rodei `pools(where:
{token0_in: [...]})`/`token1_in` contra os 14 endereços acima na v3 mainnet, e a mesma coisa em
`pairs` na v2 -- **só a Tesla (TSLAx) tem alguma pool com TVL não-trivial, e mesmo essa tem só
~$100** (`0xa7fd774e0ad54a6d2ceafb4103615f473e589cc6`, fee 0.3%). Nvidia e Coinbase têm pools com TVL
de centavos/zero. As outras 11 empresas (incluindo Apple, Microsoft, Amazon, Google -- 4 das 5 que o
usuário pediu primeiro) têm **zero pools** na Uniswap v2 ou v3 mainnet. Não é problema de indexação
nem de filtro de TVL do índice local -- é ausência real de liquidez nesse par chain/protocolo.

**Onde a liquidez de verdade está, e por que não dá pra usar**:
- **Solana (Raydium/Jupiter)**: é onde o volume de verdade das xStocks acontece -- AAPLx com ~$338k
  de liquidez e ~$2,17M de volume/24h, TSLAx com ~$499k (checado via API pública do DexScreener).
  Solana não é EVM -- não tem subgraph no mesmo formato, não tem `eth_call` pra verificação de TVL,
  não se encaixa em nada do que `graph_client.py`/`onchain_client.py`/o modelo `chain`/`protocol`
  deste app assumem. Suportar Solana seria construir uma stack paralela do zero, não "adicionar mais
  uma chain" como Polygon/Avalanche foram (mesmo schema Uniswap v3, só mudou endpoint).
- **Robinhood Chain**: certinho em teoria (Uniswap v3/v4 nativo, mesmo schema que todo o resto do
  app já fala, ~$130M/dia de volume) -- mas **não tem subgraph indexado pelo The Graph ainda**
  (verificado ao vivo no Graph Explorer, a chain nem aparece na lista de redes). Essa é a única das
  opções pesquisadas com potencial real de virar uma integração barata (mesmo código `_v3v4`
  reaproveitado) -- só falta a infraestrutura de indexação existir. **Reavaliar essa chain
  especificamente quando revisitar o assunto.**
- **Ondo Finance** (o "TSLAon" que já aparecia nos nossos dados antes dessa pesquisa): não funciona
  como uma pool de AMM pré-financiada -- faz mint/redeem contra a liquidez real da bolsa via um
  agregador (Jupiter, na Solana). Não tem uma posição de LP/IL de verdade por trás pra esse app
  modelar, independente de qual chain -- categoria de produto incompatível com o resto do app, não só
  uma questão de chain suportada.

**Decisão**: não implementar a categoria "Ação tokenizada" agora -- com a Ethereum mainnet tendo
efetivamente uma pool de $100 de TVL pra mostrar, a infraestrutura (categoria address-verificada,
filtro em `/assets`/`/pools`) não teria dado nenhum pra exibir que já justifique o esforço. Reavaliar
quando: (a) a Robinhood Chain aparecer indexada no Graph Explorer, ou (b) a liquidez de xStocks na
Ethereum mainnet crescer de forma que valha a pena. Os endereços acima já verificados podem ser
reaproveitados direto nesse momento, sem repetir a pesquisa.

## Filtro de rede (chain) separado do filtro de protocolo

`/pools` e `/assets` têm dois dropdowns de filtro distintos: "Protocolos" (versão/fork da Uniswap --
v2/v3/v4/Aerodrome/Polygon/Avalanche) e "Rede" (chain -- Ethereum/Base/Polygon/Avalanche). Não são a
mesma coisa: v2, v3 e v4 são três protocolos diferentes na MESMA rede (Ethereum), então um filtro só
por protocolo não deixa fácil "ver tudo que é Ethereum" sem marcar os três manualmente -- daí o
filtro de rede existir separado (`chain` como parâmetro de query próprio em `query_pools`/
`query_assets`, `local_db.py`, WHERE `chain = ?`). É particularmente importante em `/assets`, que não
tinha filtro de protocolo nenhum antes (um ativo não pertence a uma versão da Uniswap, só a uma
chain) -- pra assets, "Rede" é o único filtro de escopo por chain que existe.

Na busca principal (`PoolSearch.tsx`) não existe um filtro de rede separado -- os checkboxes de
"Protocolos" já cobrem isso (`protocolOptionLabel` em `format.ts` mostra a rede entre parênteses, ex:
"Uniswap v3 (Polygon)", justamente pra desambiguar "Uniswap v3" que agora existe em três redes
diferentes -- mainnet, Polygon e Avalanche -- e apareceria repetido/ambíguo numa lista achatada sem
esse rótulo). Não valeu a pena duplicar a mesma seleção em duas UIs diferentes só pra essa página.

`PoolSummary`/`PoolDetail` (schema usado pela busca ao vivo) ganharam um campo `chain` próprio
(`services/pools.py::_to_pool_summary`/`_to_pool_summary_v2`/`_get_pool_detail_v3v4`/
`_get_pool_detail_v2`, sempre `_PROTOCOL_CHAIN[protocol]`) -- antes só existia no índice local
(`PoolRecord`/`AssetRecord`). Usado pelas linhas de resultado da busca principal pra mostrar a rede
ao lado do protocolo (`formatChainLabel(pool.chain)` em `PoolSearch.tsx`).

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

## Análise avançada de faixa (`/pool/:id/simulate`)

O antigo card "Simulador de faixa" (uma faixa por vez, dentro de `/pool/:id`) foi substituído por
uma página própria (`frontend/src/pages/RangeAnalysisPage.tsx`, rota `/pool/:id/simulate`, linkada
por um card-teaser em `PoolPage.tsx` -- só aparece pra `pool.protocol !== 'v2'`, mesma regra de
antes) que compara **várias faixas de uma vez**: a que o usuário digitar ("custom") + 4 sugeridas
(estreita/média/larga por volatilidade + uma pela variação de preço realizada), com tabela
comparativa ordenável, gráfico de preço com as faixas sobrepostas (`RangeAnalysisChart.tsx`) e
gráfico de barras APR×IL (`RangeAprIlChart.tsx`). Não se aplica a v2 pelo mesmo motivo de sempre
(sem liquidez concentrada, sem série horária -- `get_pool_hour_data` já lança `GraphQueryError`
pra v2).

**Endpoint único, sem multiplicar custo de cota por faixa**: `POST /api/indicators/range-analysis`
(`routers/indicators.py::analyze_range`, substituiu o antigo `range-simulate`/`simulate_range` --
schemas `RangeAnalysisRequest`/`RangeAnalysisResponse`/`RangeScenario` em `schemas.py`) busca o
histórico horário + diário + detalhe do pool **uma única vez** e roda
`indicators.replay_range_against_history` localmente pra cada cenário (custom + as 4 sugeridas,
quando `include_suggested=true`) -- nenhuma chamada extra ao Graph por faixa comparada.

**Achado real corrigido nesta mudança**: o endpoint antigo calculava `annualized_volatility` a
partir dos preços **horários** mas com o `periods_per_year` padrão da função (365, pensado pra
fechamentos diários) -- o resultado saía ~√24 ≈ 4,9x menor que o real. Esse campo nunca tinha sido
exibido no frontend até agora (era só ruído morto na resposta), mas a página nova constrói as
faixas sugeridas em cima desse número, então precisava estar certo. Fix: `analyze_range` calcula
`annualized_volatility` a partir dos fechamentos **diários** (já buscados na mesma chamada) --
mesma convenção já usada em `routers/pools.py` pros indicadores 7d/30d, sem precisar de um
`periods_per_year` alternativo pra horas.

**As duas funções de sugestão são puras, em `indicators.py`** (mesmo padrão do resto do módulo --
sem I/O, testadas isoladamente em `test_indicators.py`):
- `suggest_range_by_volatility(current_price, annualized_vol, horizon_days, k)`: faixa
  log-simétrica `current_price * exp(∓k·vol·sqrt(horizon_days/365))` -- `k` em
  `_SUGGESTED_VOLATILITY_K` (`routers/indicators.py`: narrow=0.5, medium=1.0, wide=2.0). Assume
  log-normalidade dos retornos (mesma convenção de `annualized_volatility`) -- aproximação, não
  previsão; o rodapé da página avisa isso.
- `suggest_range_from_realized(daily_closes)`: `(min, max)` da série diária -- sem suposição de
  distribuição nenhuma, contraponto às três acima.

**Janela histórica tem teto de 41 dias** (`_MAX_HISTORY_DAYS` em `routers/indicators.py`, espelhado
no frontend como `MAX_HISTORY_DAYS`) -- não é um número arbitrário: `poolHourDatas` é buscado com
`first: history_days * 24`, e o Graph limita `first` a 1000. 41×24 = 984 (abaixo do teto); 42×24 =
1008 já estoura. Passar disso faria a query horária vir truncada sem erro nenhum (o Graph
simplesmente devolve os últimos `first` registros), inflando silenciosamente a fração "tempo em
faixa" ao ignorar parte do período pedido -- por isso o backend clampa (`min(req.history_days,
_MAX_HISTORY_DAYS)`) em vez de confiar no `max` do input do frontend. `RangeAnalysisResponse` devolve
`history_days`/`entry_price` com os valores REALMENTE usados (já clampado/resolvido) -- o frontend
usa esses campos pra tudo que depende deles (rodapé, escala do "líquido USD" por cenário), nunca o
que foi enviado no request, senão diverge silenciosamente quando o clamp entra em ação ou quando o
usuário edita o formulário sem reenviar.

**Pegadinha de UX que já mordeu nesta feature**: o campo "preço de entrada" começa **vazio**, não
pré-preenchido com o preço atual. Se preenchido com o preço atual (ou deixado igual por engano), IL
fica **zerado pra todo cenário** (`impermanent_loss_v3` dá 0 quando entrada == saída, e nesse
horizonte curto o preço atual quase sempre está perto do fechamento mais recente) -- as colunas de
IL/break-even da tabela e metade do gráfico APR×IL ficam mortas, sem nenhum erro visível. Vazio =
backend usa o preço no INÍCIO da janela histórica como entrada (mesmo default do simulador antigo),
que é o que produz um IL diferente de zero de verdade.

## Índice local (SQLite): /assets, /pools e autocomplete

Além da busca ao vivo no Graph (`/api/pools/search`), o app mantém um índice local (SQLite,
`backend/data/local_index.db`, gitignored) com todos os ativos e pools "relevantes" (TVL/reserva >=
`Settings.index_min_tvl_usd`, default $1.000 -- mesmo piso já usado em `get_related_pools`). Serve
três coisas: as páginas `/assets` e `/pools` (tabelas ordenáveis/filtráveis/paginadas server-side, ver
`routers/local_index.py`), e o autocomplete do campo de busca principal
(`GET /api/index/assets/suggest`, usado por `PoolSearch.tsx` e `TokenMultiSelect.tsx`) -- que por
isso não gasta cota do Graph a cada tecla digitada, já que consulta só o SQLite local.

**`suggest_assets` (`local_db.py`) agrupa por `symbol`, mantendo só a linha de maior TVL de cada
grupo.** Achado real ao adicionar Polygon/Avalanche em 2026-09-10: sem agrupar, um símbolo popular
(USDC, WETH) passou a aparecer até 4x no mesmo dropdown (uma linha por chain) -- com o `limit` padrão
de 8, isso chegou a consumir 6 das 8 posições pra "USDC", escondendo símbolos de verdade diferentes
(ex: USDCV, ou tokens homônimos falsos que `_is_plausible_pool`/categoria não filtram porque isso é
autocomplete de ativo, não de pool). Não perde nenhuma chain da busca em si -- todo o resto do fluxo
(clique na sugestão, chip do `TokenMultiSelect`) já seleciona por `symbol`, não por `chain`
específica, então mostrar só a linha de maior TVL por símbolo é estritamente melhor pra
descoberta sem mudar o que a busca resultante inclui. As linhas de sugestão mostram a rede
(`formatChainLabel(asset.chain)`) pra deixar claro que aquele resultado é cross-chain, mesmo já
agrupado.

**Não atualiza sozinho.** Só quando alguém clica em "Atualizar lista" (`POST /api/index/refresh`,
`IndexRefreshBar.tsx`, usado em ambas as páginas) é que `services/index_builder.py` faz um crawl
completo dos 6 subgraphs (em paralelo) e substitui o conteúdo inteiro das tabelas de uma vez. Motivo
de ser manual: com o piso de $1k, o total observado em 2026-09-10 (depois de adicionar Polygon e
Avalanche) foi **~36 mil ativos / ~43 mil pools**, exigindo ~90-150 consultas ao gateway e **~4
minutos** de execução (crawl de todo protocolo v3-like inclui `poolDayData` aninhado por pool, ver
abaixo) -- barato o bastante em cota pra não importar
(uma fração pequena da cota mensal de 100k), mas caro o bastante em tempo pra não rodar a cada
carregamento de página. A paginação usa cursor (`id_gt`), não `skip`/`offset` -- o Graph limita
`skip` a 5000 e a v3 mainnet sozinha já passa disso com folga (~7900 pools com TVL >= $1k, medido
antes desse teto entrar em vigor). `_PAGE_SIZE` é 500 (não 1.000) desde que o crawl passou a incluir
`poolDayData` aninhado -- achado real em 2026-09-10: com `first: 1000` e 30 dias aninhados por pool
(até 30 mil entidades por página), um crawl de v3 falhou com "bad indexers: Timeout/Unavailable" no
gateway; página menor reduz o payload por requisição e a chance de bater nisso, ao custo do dobro de
páginas (`_MAX_PAGES` dobrado também, mesmo teto total de pools).

**Volume 1d/30d, Vol. 1d/TVL e APR (30d) por pool/ativo** (colunas em `/pools`, filtros em
`/pools`/`/assets`/busca principal) vêm do crawl, não de uma consulta extra: `poolDayData` é um campo
derivado (`@derivedFrom`) do schema do `Pool` em qualquer protocolo v3-like (v3/v4/Aerodrome/Polygon/
Avalanche), então pedir
`poolDayData(first: 30, orderBy: date, orderDirection: desc) { date volumeUSD feesUSD }` aninhado
dentro da própria query de crawl (`_INDEX_POOLS_QUERY`) traz os últimos 30 dias de cada pool na MESMA
chamada ao gateway, sem custo extra de cota -- confirmado por introspecção e teste ao vivo em
2026-09-10. **v2 não participa** -- `PairDayData` não tem relação reversa pra `Pair` no schema do
subgraph comunitário da Uniswap (só o endereço cru em `pairAddress`, sem campo `pair`), então não há
como pedir isso aninhado; replicar via uma segunda rodada de consultas em lote (como
`_fetch_recent_day_data_batch` já faz pra enriquecer resultados de busca, só que pra ~30 mil pools
v2 de uma vez) seria caro demais pro refresh manual. Por isso essas quatro colunas ficam **NULL**
(não 0) pra pools/ativos v2 -- ver comentário em `local_db.init_schema` sobre por que é NULL e não
0 (0 seria indistinguível de "medido e sem atividade", e corromperia ordenação/filtro por essas
colunas). Um filtro `min_*`/`max_*` nessas colunas exclui silenciosamente pools/ativos v2 (comparação
SQL com NULL nunca é verdadeira) -- o frontend mostra um aviso disso quando algum desses filtros está
preenchido em `/pools`/`/assets`. Pra ativos, `volume_1d_usd`/`volume_30d_usd` são a soma dessas
métricas das pools onde o ativo aparece que TÊM a métrica medida (todo protocolo v3-like contribui);
um ativo fica com essas colunas NULL só se TODAS as suas pools forem v2.

Se algum dos 6 protocolos falhar durante um refresh, os outros ainda são salvos (índice fica
parcialmente atualizado, não é tudo-ou-nada) e o motivo fica em `protocol_errors` na resposta --
`IndexRefreshBar` mostra um aviso quando isso acontece. Só se os 6 falharem é que o índice existente
é preservado sem alteração (nunca sobrescreve com um índice vazio).

**Achado real ao construir esse índice pela primeira vez**: ordenar por TVL descendente expôs dois
padrões de dado corrompido/manipulado que a busca ao vivo (que também ordena por TVL) já estava
igualmente exposta a, só que sem ter sido notado antes por não existir uma lista completa pra olhar.
Ambos ficaram documentados como `_is_plausible_pool()` em `services/pools.py` (usado tanto no índice
quanto em `search_pools`/`get_related_pools` -- não é exclusivo do índice):
- **TVL fisicamente impossível** (`_MAX_SANE_TVL_USD`, $10B): uma pool v2 chegou a reportar
  `reserveUSD` de ~3,5e+34 (maior que todo o mercado cripto junto) -- provavelmente um token com
  decimals manipulados enganando o cálculo de preço derivado do subgraph.
- **"Taxa" tipo honeypot** (`_MAX_SANE_FEE_TIER`, 10% -- exceto a sentinel de taxa dinâmica da v4,
  `_DYNAMIC_FEE_SENTINEL`) **combinada com volume histórico quase nulo** (`_MIN_PLAUSIBLE_VOLUME_USD`,
  $100 acima de `_MIN_TVL_REQUIRING_VOLUME_USD` = $1M de TVL): pools com `feeTier` tipo 999990
  (99,999%) e centenas de milhões/bilhões de TVL "fake", volume histórico de $0 a poucos dólares (uma
  chegou a mostrar exatos $1,00 de volume pra um TVL de $1B -- parece ter sido calibrado pra escapar
  de um filtro ingênuo de "volume zero"). Esse é um filtro heurístico, não uma garantia -- se aparecer
  lixo novo desse tipo, ajuste os limiares em vez de assumir que "não tem mais nenhum".

Categoria de ativo (`token_categories.py`, ex: "Stablecoin (USD)", "ETH / LST", "BTC") é um
mapeamento **fixo por símbolo, não verificado on-chain** -- qualquer um pode criar um token com esse
mesmo símbolo (mesmo aviso já existente em `PoolOverview` sobre confiar no endereço do contrato, não
no nome/símbolo). "Principais pares" de cada ativo (usado como aproximação de "correlação") é
calculado a partir das próprias pools indexadas -- soma o TVL por símbolo de contraparte e pega os 3
maiores -- não é correlação de preço calculada.

Frontend: `SortableHeader.tsx` foi extraído de `PoolSearch.tsx` pra ser reaproveitado por
`AssetsPage.tsx`/`PoolsIndexPage.tsx` (mesmo componente visual, mas cada página ordena/pagina
server-side via `sort`/`order`/`limit`/`offset`, diferente de `PoolSearch` que ordena os até 50
resultados no cliente). As duas tabelas usam classes de grid próprias
(`.pool-list__header--assets`/`--pools-index`) porque têm número de colunas diferente da lista de
busca principal (sem coluna de "#").

## Filtros avançados de busca (sigla exata, par de tokens, ocultar sem atividade)

As três telas de busca/listagem (`PoolSearch.tsx`, `/assets`, `/pools`) têm um painel de "Filtros
avançados" com: busca por **sigla/nome exato** em vez de "contém"; busca por **par de tokens**
(Token A/Token B, cada um um `TokenMultiSelect` -- digita, aparece autocomplete, clica, vira chip
com "x" pra remover; dá pra selecionar vários de cada lado, ver seção própria abaixo); **ocultar
pools sem atividade** (volume histórico zero); piso de TVL mínimo; filtros de faixa (min/max) de
volume 1d/30d, Vol. 1d/TVL e APR (ver seção "Índice local" acima -- `/pools`/`/assets` filtram o
SQLite inteiro, a busca principal filtra só depois de buscar, ver ressalva abaixo); filtro de
protocolo; e nº de itens por página (25/50/100).

O ponto que não é óbvio: a maioria desses filtros é aplicada na própria consulta (GraphQL `where`
pra `PoolSearch`, SQL `WHERE` pra `/assets`/`/pools`), não depois de buscar -- "ocultar sem
atividade", em particular, substituiu um toggle antigo que filtrava client-side depois do fetch
(isso desperdiçava posições do `limit` com pools mortas; agora o próprio `limit` já é só de
resultados relevantes). **Exceção**: os filtros de volume 1d/30d/Vol.1d/TVL/APR na busca principal
(`PoolSearch.tsx`) são pós-filtro, porque dependem de `poolDayData` (enriquecimento que só roda
depois de já ter os candidatos truncados por `limit`) -- ver seção "Filtros numéricos (volume/APR)
na busca ao vivo" abaixo.

- **`services/pools.py`**: `_search_query_v3v4(exact)`/`_search_query_v2(exact)` são *funções*, não
  constantes -- "exato" muda o nome do campo GraphQL (`symbol` vs `symbol_contains_nocase`), o que só
  dá pra parametrizar como texto da query, não como variável. Isso vale só pra busca por TEXTO LIVRE
  (`q`); a busca por par/lista de chips usa `symbol_in` (sempre exata -- os valores vêm de seleção no
  autocomplete, não de texto digitado, então `exact` não se aplica a ela, ver próxima seção). Já
  `min_tvl`/`min_volume` (piso de TVL/"sem atividade") são variáveis GraphQL de verdade (0 = sem
  efeito), então não multiplicam o número de templates. Verificado por consulta real em 2026-09-09:
  `symbol`/`name` exatos existem em `Token_filter` tanto em v2 quanto v3, e combinam com filtros de
  TVL/volume no mesmo `where` (semântica AND).
- **Busca por par sempre consulta as duas ordens** (`ab`/`ba`, dois aliases) -- token0/token1 é
  canônico por endereço (menor primeiro), não por qual token "parece" ser o principal. Confirmado ao
  vivo: WETH/USDC de verdade tem quase todo o TVL do lado `token0=USDC`/`token1=WETH`, não o
  contrário -- sem consultar as duas ordens, a busca por par perderia a maioria dos resultados reais.
- **`local_db.py`** replica a mesma lógica em SQL (`query_pools`/`query_assets` recebem `exact`,
  `hide_inactive`, e `query_pools` também `token_a`/`token_b` como listas) -- exato usa
  `= ? COLLATE NOCASE` (não `=` puro, que é case-sensitive no SQLite) pra continuar case-insensitive
  como o "contém"; já os `IN (...)` do filtro por chips (token_a/token_b) NÃO usam COLLATE NOCASE de
  propósito, mesma razão do `symbol_in` do GraphQL abaixo (símbolos vêm do índice, capitalização
  exata). Pra "ocultar sem atividade" funcionar em `/assets` (não só em `/pools`), a tabela `assets`
  ganhou uma coluna `total_volume_usd` (soma do volume das pools onde o ativo aparece, calculada em
  `index_builder.py` junto com `total_tvl_usd`) -- um arquivo `local_index.db` de antes dessa coluna
  existir é migrado on-the-fly via `_ensure_column` (`ALTER TABLE ... ADD COLUMN`) em vez de precisar
  apagar o cache manualmente.
- **`PoolSearch.tsx`**: os filtros avançados não vão pra URL (mesma decisão já tomada pra
  ordenação/toggle antigo -- resetam ao voltar da página de detalhe de um pool). Como a busca por par
  não depende do campo `q` mudar, existe um `searchTrigger` (contador incrementado a cada submit) só
  pra forçar o efeito de busca a rodar de novo mesmo quando `q` continua vazio/igual.

### Token A/Token B: multi-select com chips (`TokenMultiSelect.tsx`) e `symbol_in`

Token A e Token B nos filtros avançados (`PoolSearch.tsx` e `/pools`) são campos de múltipla seleção
com autocomplete, não texto livre: digita, aparece uma lista de sugestões (mesmo
`GET /api/index/assets/suggest` usado pelo campo de busca principal), clica numa sugestão pra
"selecionar" (vira um chip ao lado, com "x" pra remover) -- digitar sem clicar NÃO adiciona nada ao
filtro, só filtra a lista de sugestões. Cap de 8 chips por campo (`MAX_TOKENS` em
`TokenMultiSelect.tsx`), só pra UX (não é limite técnico -- ver próximo parágrafo).

Cada lado (Token A, Token B) é uma **lista** de símbolos, não mais uma sigla só -- ex: Token A =
[WETH, WBTC], Token B = [USDC, USDT] acha pools de qualquer combinação entre os dois grupos, em
qualquer ordem de token0/token1 (`ab: token0 IN A, token1 IN B` + `ba: token0 IN B, token1 IN A`).
Isso é feito com o filtro `symbol_in: [String!]` do `Token_filter` do subgraph (confirmado por
introspecção/consulta real em 2026-09-10, existe em v2 e v3) em vez de gerar um alias por combinação
de tokens -- uma lista de N símbolos custa a mesma query que uma lista de 1, então o número de chips
selecionados **não** multiplica o número de aliases/chamadas ao gateway (diferente de antes, quando
"par" só aceitava uma sigla de cada lado). Efeito colateral bom: sem essa mudança, uma busca por par
de duas siglas sozinha já levava ~20-25s (4 protocolos, 2 ordens cada); com `symbol_in` a mesma busca
caiu pra ~5-6s, mesmo com múltiplos símbolos por lado.

Se só um dos dois lados tem chips selecionados (ex: só Token A), vira busca por **lista única**:
qualquer um daqueles símbolos em qualquer posição (`token0_in` OU `token1_in`) -- um modo a mais além
de "por par" e "por texto livre" (`search_pools` em `services/pools.py` despacha entre os três, texto
livre só quando nenhum token_a/token_b vem preenchido). `routers/pools.py`'s `token_a`/`token_b` são
parâmetros de query repetíveis (`?token_a=WETH&token_a=WBTC`), não mais uma string só.

`symbol_in` **não tem variante `_in_nocase`** -- os símbolos vêm do índice local (escolhidos no
autocomplete, com a capitalização exata como indexada), não de texto livre digitado, então isso não é
um problema na prática (diferente da busca por texto livre, que continua usando
`_contains_nocase`/exato case-insensitive).

### Filtros numéricos (volume/APR) na busca ao vivo

Os mesmos quatro filtros de faixa disponíveis em `/pools`/`/assets` (volume 1d/30d, Vol. 1d/TVL, APR
30d, min/max) existem também na busca principal (`PoolSearch.tsx`), mas funcionam diferente por
baixo -- lá é um `WHERE` sobre o SQLite inteiro (recall perfeito); aqui é **pós-filtro** sobre um
conjunto de candidatos já truncado, porque essas métricas dependem de `poolDayData`/`pairDayDatas`
(enriquecimento que só roda depois de já ter os candidatos da busca "crua", igual o resto de
`search_pools` já fazia antes desses filtros existirem).

Isso cria um problema real se não tratado: o fluxo normal já corta pra `limit` (25/50/100) por TVL
*antes* de buscar o histórico -- filtrar por APR/volume DEPOIS desse corte poderia devolver uma lista
vazia mesmo havendo pools de TVL baixo que passariam no filtro, só que ficaram fora do corte por TVL.
Por isso, quando qualquer um desses filtros está ativo, `search_pools` (`services/pools.py`) soma
`_FILTERED_CANDIDATE_EXTRA` (60) a `limit` pro corte pré-enriquecimento, em vez de usar `limit` puro
-- tem que ser uma soma, não um piso tipo `max(limit, 60)`: com `limit=100` (a opção mais alta da UI)
um piso de 60 não alargaria nada, já que 100 já é >= 60. Só depois de filtrar é que corta pro `limit`
de verdade. `_fetch_recent_day_data_batch` (chamada uma vez por protocolo, só com os candidatos
daquele protocolo) pagina até 2000 linhas (ver comentário na função) e cada pool consome até 30 (uma
por dia) -- então ela cobre com folga até ~66 candidatos NUM SÓ protocolo; no pior caso (busca
concentrada num único protocolo, ex: filtro de protocolo == v3) com `limit=100`, o corte
pré-enriquecimento vira 160, passando desse teto seguro. Candidatos "no fim da fila" nesse cenário (a
ordem das linhas devolvidas pelo subgraph não agrupa por pool) podem ficar com o histórico incompleto
e aparecer com volume/APR zerado mesmo tendo atividade real -- por isso o frontend mostra um aviso de
que o filtro "pode não pegar pools de TVL bem baixo" quando algum desses campos está preenchido.

Ao contrário do índice local, a busca ao vivo **mede de verdade** volume 1d/30d/APR pra pools v2
também (não fica NULL) -- `_fetch_recent_day_data_batch` já buscava `pairDayDatas` em lote pra v2
antes desses filtros existirem (usado pelas colunas Vol. 1d/30d que já existiam na tabela de
resultados), só que ali o custo é por um punhado de candidatos (`limit + _FILTERED_CANDIDATE_EXTRA`),
não pelos ~30 mil pools v2 de um crawl completo do índice -- é essa diferença de escala que torna
inviável fazer o mesmo pro índice local (ver seção "Índice local" acima).

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
- **Python/Node do sistema são antigos demais** (Python 3.8, Node 12 — Ubuntu 20.04) e nem sempre
  existem no PATH. Por isso o toolchain inteiro (Python + Node) vem de um único ambiente conda
  (Miniforge), definido em `environment.yml` (`name: provedor-liquidez`, Python 3.12 + Node 24) --
  criar/atualizar com `conda env create -f environment.yml` ou `make setup` (que também roda
  `pip install`/`npm install` dentro do ambiente). `scripts/dev.sh` já resolve e ativa esse ambiente
  sozinho (via `conda activate` dentro do `setsid`, com fallback pra achar o `conda` mesmo fora do
  PATH -- ver `find_conda_base()` no script e o mesmo padrão em `CONDA_EXE` no `Makefile`). Se for
  rodar comandos manuais fora do script/Makefile, `conda activate provedor-liquidez` primeiro,
  senão vai bater em `SyntaxError`/`TypeError: 'type' object is not subscriptable` (Python velho) ou
  erro de sintaxe (Node velho). Um `backend/.venv` antigo (criado via `uv`) pode ainda existir no
  disco mas não é mais referenciado por nada -- é seguro apagar.
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
make test        # backend: matemática pura, não precisa de API key
make typecheck    # frontend: type-check (não tem suíte de testes JS ainda)
# equivalente sem make: conda activate provedor-liquidez && cd backend && pytest
#                       conda activate provedor-liquidez && cd frontend && npx tsc --noEmit -p tsconfig.app.json
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
  indicators.py             # matemática pura (IL, APR, volatilidade, replay de faixa) — sem I/O
  graph_client.py            # cliente HTTP fino pro gateway do The Graph (key nunca sai daqui)
  usage_tracker.py           # contador local de consultas
  services/pools.py          # queries GraphQL ao vivo + mapeamento pros schemas
  services/index_builder.py  # crawl completo pra reconstruir o índice local (ver seção acima)
  local_db.py                 # SQLite do índice local (assets/pools/index_meta)
  token_categories.py         # mapeamento fixo símbolo -> categoria (ver seção acima)
  routers/                    # rotas FastAPI (inclui local_index.py, prefixo /api/index)
  schemas.py                  # modelos Pydantic (request/response)
  config.py                   # settings via pydantic-settings (.env)

frontend/src/
  api/client.ts               # wrapper fetch tipado pro backend
  components/                 # um componente por seção do dashboard
  components/SortableHeader.tsx  # cabeçalho de coluna clicável, reaproveitado em 3 tabelas
  pages/PoolPage.tsx          # página de detalhe do pool (rota /pool/:id)
  pages/AssetsPage.tsx        # lista de ativos (rota /assets)
  pages/PoolsIndexPage.tsx    # lista completa de pools (rota /pools)
  format.ts                    # helpers de formatação (USD, %, preço, data)
```

## Navegação (react-router-dom)

Quatro rotas, definidas em `App.tsx` (que também é o layout compartilhado — header/footer/`UsageBadge`
ficam fora do `<Routes>`): `/` é a busca (`components/PoolSearch.tsx`, que já é a "página" — não tem
um `SearchPage.tsx` separado), `/pool/:id` é o detalhe (`pages/PoolPage.tsx`), `/assets` é a lista de
ativos e `/pools` a lista completa de pools (ambas do índice local, ver seção acima). `WIDE_PATH_PREFIXES`
em `App.tsx` decide quais rotas usam o layout largo (`.app--wide`) -- inclui as três últimas. O `id` da
rota de detalhe é o id prefixado por protocolo (`v3:0xabc...`) vindo de `PoolSummary.id`, sempre
passado por `encodeURIComponent` ao montar o link/navigate (por causa do `:`) e por
`decodeURIComponent` ao ler de volta em `useParams()`.

O termo de busca fica sincronizado com a URL (`/?q=termo`, via `useSearchParams` dentro do próprio
`PoolSearch`) — é assim que o botão voltar do navegador consegue restaurar a lista depois de abrir um
pool: `PoolSearch` desmonta ao navegar pra `/pool/:id` (perde o estado local), mas ao voltar pra `/`
o efeito que dispara a busca roda de novo a partir do `q` da URL. Isso custa uma busca nova ao Graph
a cada "voltar" (aceitável frente ao limite de 100k/mês) — ordenação de coluna e o toggle de "ocultar
sem volume" não são persistidos na URL, só o termo.

A página de pool usa mais largura que a busca (classe `.app--wide` em `App.css`, aplicada em `App.tsx`
via `useLocation().pathname.startsWith('/pool/')`) — é por isso que existe mais espaço lá pra
estatísticas em 4 colunas.
