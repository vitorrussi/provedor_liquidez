from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    graph_api_key: str = ""
    # ID oficial do subgraph Uniswap v3 mainnet (confirmado em developers.uniswap.org
    # e no Graph Explorer em 2026-09). Pode ser sobrescrito via .env se precisar
    # apontar para outra rede/deployment.
    uniswap_v3_subgraph_id: str = "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV"

    cors_origins: list[str] = ["http://localhost:5173"]

    # Plano free do Subgraph Studio: 100k queries/mês. Usado só para estimar
    # quanto resta -- a fonte de verdade é o dashboard do Studio.
    graph_monthly_query_limit: int = 100_000

    @property
    def graph_gateway_url(self) -> str:
        return f"https://gateway.thegraph.com/api/{self.graph_api_key}/subgraphs/id/{self.uniswap_v3_subgraph_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
