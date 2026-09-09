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

    cors_origins: list[str] = ["http://localhost:5173"]

    # Plano free do Subgraph Studio: 100k queries/mês. Usado só para estimar
    # quanto resta -- a fonte de verdade é o dashboard do Studio.
    graph_monthly_query_limit: int = 100_000

    # RPC público (sem API key) usado só pra verificar o TVL de um pool via
    # saldo real on-chain (balanceOf) -- o campo totalValueLockedUSD do
    # subgraph pode divergir do real (bug de tracking incremental, ver
    # CLAUDE.md). Pode trocar por um endpoint próprio (Infura/Alchemy) via
    # .env se esse público ficar instável/limitado.
    eth_rpc_url: str = "https://ethereum-rpc.publicnode.com"

    def graph_gateway_url(self, protocol: str = "v3") -> str:
        subgraph_id = {
            "v2": self.uniswap_v2_subgraph_id,
            "v3": self.uniswap_v3_subgraph_id,
            "v4": self.uniswap_v4_subgraph_id,
        }[protocol]
        return f"https://gateway.thegraph.com/api/{self.graph_api_key}/subgraphs/id/{subgraph_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
