from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from . import request_log
from .config import get_settings
from .routers import indicators, local_index, pools
from .schemas import GraphRequestLogEntry, GraphUsageResponse
from .usage_tracker import get_usage

app = FastAPI(title="Provedor de Liquidez API", version="0.1.0")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pools.router)
app.include_router(indicators.router)
app.include_router(local_index.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/graph-usage", response_model=GraphUsageResponse)
def graph_usage():
    stats = get_usage()
    return GraphUsageResponse(month=stats.month, used=stats.used, limit=stats.limit, remaining=stats.remaining)


@app.get("/api/graph-usage/log", response_model=list[GraphRequestLogEntry])
def graph_usage_log(limit: int = Query(50, ge=1, le=500)):
    entries = request_log.read_recent(limit)
    return [
        GraphRequestLogEntry(
            timestamp=e.timestamp,
            operation=e.operation,
            variables=e.variables,
            status=e.status,
            duration_ms=e.duration_ms,
            error=e.error,
        )
        for e in entries
    ]
