from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    graph_api_key: str = ""
    # IDs oficiais dos subgraphs Uniswap mainnet (confirmados em developers.uniswap.org
    # e no Graph Explorer em 2026-09). Podem ser sobrescritos via .env se precisar
    # apontar para outra rede/deployment.
    uniswap_v2_subgraph_id: str = "A3Np3RQbaBA6oKJgiwDJeo5T3zrYfGHPWFYayMwtNDum"
    uniswap_v3_subgraph_id: str = "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV"
    uniswap_v4_subgraph_id: str = "DiYPVdygkfjDWhbxGSqAQxwBKmfKnkWQojqeM2rkLb3G"
    # Aerodrome Slipstream (fork da Uniswap v3, roda na Base) -- não é um
    # subgraph oficial/mantido pela Aerodrome (não tem SLA), mas verificado
    # em 2026-09-09: ativo, sem erros de indexação, e o `factories.id`
    # retornado bate com o CLFactory real da Aerodrome on-chain. Ver
    # CLAUDE.md, seção "Aerodrome Slipstream (Base)".
    aerodrome_slipstream_subgraph_id: str = "GENunSHWLBXm59mBSgPzQ8metBEp9YDfdqwFr91Av1UM"
    # Uniswap v3 em Polygon e Avalanche -- mesmo schema da v3 mainnet
    # (reaproveita todo o código de services/pools.py::_search_v3v4 e
    # afins), subgraphs comunitários (não publicados pela Uniswap Labs no
    # gateway, sem SLA -- igual Aerodrome). Verificados em 2026-09-10:
    # `factories.id` de cada um bate com o endereço real da Uniswap V3
    # Factory na respectiva chain (Polygon: 0x1F98431c8aD98523631AE4a59f267346ea31F984,
    # o mesmo endereço determinístico usado na maioria das chains v3;
    # Avalanche: 0x740b1c1de25031C31FF4fC9A62f554A55cdC1baD, confirmado via
    # Snowtrace -- endereço diferente do padrão porque a Avalanche não
    # recebeu o deploy determinístico via CREATE2 nas mesmas condições),
    # `hasIndexingErrors: false`, dados recentes. Ver CLAUDE.md, seção
    # "Uniswap v3 em Polygon e Avalanche".
    uniswap_v3_polygon_subgraph_id: str = "3hCPRGf4z88VC5rsBKU5AA9FBBq5nF3jbKJG7VZCbhjm"
    uniswap_v3_avalanche_subgraph_id: str = "GVH9h9KZ9CqheUEL93qMbq7QwgoBu32QXQDPR6bev4Eo"

    cors_origins: list[str] = ["http://localhost:5173"]

    # Plano free do Subgraph Studio: 100k queries/mês. Usado só para estimar
    # quanto resta -- a fonte de verdade é o dashboard do Studio.
    graph_monthly_query_limit: int = 100_000

    # RPCs públicos (sem API key) usados só pra verificar o TVL de um pool via
    # saldo real on-chain (balanceOf) -- o campo totalValueLockedUSD do
    # subgraph pode divergir do real (bug de tracking incremental, ver
    # CLAUDE.md). Pode trocar por um endpoint próprio (Infura/Alchemy) via
    # .env se esse público ficar instável/limitado. Um RPC por chain (nunca
    # compartilhado entre chains, ver `_rpc_url_for_protocol` em
    # services/pools.py) -- `eth_rpc_url` é Ethereum mainnet (v2/v3/v4),
    # `base_rpc_url` é Base (Aerodrome Slipstream), `polygon_rpc_url` é
    # Polygon PoS, `avalanche_rpc_url` é Avalanche C-Chain. `eth_chainId`
    # conferido em cada um (0x89=137 Polygon, 0xa86a=43114 Avalanche C-Chain)
    # em 2026-09-10 antes de usar.
    eth_rpc_url: str = "https://ethereum-rpc.publicnode.com"
    base_rpc_url: str = "https://mainnet.base.org"
    polygon_rpc_url: str = "https://polygon-bor-rpc.publicnode.com"
    avalanche_rpc_url: str = "https://avalanche-c-chain-rpc.publicnode.com"

    # Piso de TVL (pools v3/v4/aerodrome) / reserva (pares v2) usado ao
    # reconstruir o índice local de ativos/pools (ver services/index_builder.py
    # e local_db.py) -- mesmo piso já usado como filtro de "poeira" em
    # get_related_pools. Só afeta o índice local (/api/index/*), não a busca
    # ao vivo (/api/pools/search).
    index_min_tvl_usd: float = 1000.0

    def graph_gateway_url(self, protocol: str = "v3") -> str:
        subgraph_id = {
            "v2": self.uniswap_v2_subgraph_id,
            "v3": self.uniswap_v3_subgraph_id,
            "v4": self.uniswap_v4_subgraph_id,
            "aerodrome": self.aerodrome_slipstream_subgraph_id,
            "polygon": self.uniswap_v3_polygon_subgraph_id,
            "avalanche": self.uniswap_v3_avalanche_subgraph_id,
        }[protocol]
        return f"https://gateway.thegraph.com/api/{self.graph_api_key}/subgraphs/id/{subgraph_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
