import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from .agent_runtime import classifier_from_settings
from .alchemy_discovery import AlchemyIncidentDiscovery
from .auth import require_user
from .config import get_settings
from .discovery import (
    ChainabuseClient,
    DiscoveryProviderError,
    DiscoveryUnavailableError,
    GoPlusAddressClient,
    IncidentNotFoundError,
)
from .models import CaseCreate, CaseResponse, ChainName
from .movement import (
    AlchemyHistoricalMovementDetector,
    BitqueryRealtimeMovementDetector,
    HybridMovementProvider,
)
from .providers import JsonRpcProvider, RpcProviderError
from .repository import repository_from_settings
from .taskmaster import (
    FirestoreMonitoringRepository,
    GooglePubSubPublisher,
    InMemoryMonitoringRepository,
    Taskmaster,
    decode_pubsub,
)
from .workflow import CaseWorkflow

settings = get_settings()
logging.basicConfig(level=settings.log_level)
repository = repository_from_settings(settings)
rpc_provider = JsonRpcProvider(
    {"ethereum": settings.ethereum_rpc_url, "base": settings.base_rpc_url},
    timeout_seconds=settings.rpc_timeout_seconds,
)
provider = HybridMovementProvider(
    rpc_provider,
    historical=(
        AlchemyHistoricalMovementDetector(
            settings.alchemy_api_key,
            timeout_seconds=settings.rpc_timeout_seconds,
        )
        if settings.alchemy_api_key
        else None
    ),
    realtime=(
        BitqueryRealtimeMovementDetector(
            settings.bitquery_access_token,
            endpoint=settings.bitquery_endpoint,
            timeout_seconds=settings.rpc_timeout_seconds,
        )
        if settings.bitquery_access_token
        else None
    ),
)
classifier = classifier_from_settings(settings)

goplus = GoPlusAddressClient(
    base_url=settings.goplus_base_url,
    access_token=settings.goplus_access_token,
)
chainabuse = ChainabuseClient(
    api_key=settings.chainabuse_api_key,
    base_url=settings.chainabuse_base_url,
)
discovery = (
    AlchemyIncidentDiscovery(
        api_key=settings.alchemy_api_key,
        timeout_seconds=settings.rpc_timeout_seconds,
        max_pages=settings.alchemy_discovery_max_pages,
        goplus=goplus,
        chainabuse=chainabuse,
    )
    if settings.alchemy_api_key
    else None
)
workflow = CaseWorkflow(repository, provider, classifier, discovery=discovery)
taskmaster = None
bearer = HTTPBearer(auto_error=False)


async def require_internal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "authenticated internal caller required")
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(
            credentials.credentials,
            GoogleRequest(),
            audience=settings.cloud_run_service_url,
        )
    except Exception as exc:
        raise HTTPException(401, "invalid internal identity token") from exc
    if settings.internal_service_account and claims.get("email") != settings.internal_service_account:
        raise HTTPException(403, "internal caller is not authorized")
    return claims


async def owned_case(case_id: str, user: dict):
    case = await repository.get(case_id)
    if not case:
        raise HTTPException(404, "case not found")
    if case.owner_user_id != user.get("sub"):
        raise HTTPException(404, "case not found")
    return case


class DormantRequest(BaseModel):
    case_id: str = Field(min_length=4, max_length=80)
    chain: ChainName
    address: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")
    cursor_block: int = Field(ge=0)


@asynccontextmanager
async def lifespan(_):
    global taskmaster
    await repository.initialize()
    if hasattr(repository, "client") and repository.client is not None:
        monitor_repo = FirestoreMonitoringRepository(repository.client)
        publisher = GooglePubSubPublisher(settings.google_cloud_project, settings.pubsub_topic)
    else:
        monitor_repo = InMemoryMonitoringRepository()
        publisher = GooglePubSubPublisher(settings.google_cloud_project, settings.pubsub_topic)
    taskmaster = Taskmaster(
        monitor_repo,
        provider,
        publisher,
        settings.monitoring_max_blocks,
        settings.trace_max_depth,
    )
    workflow.taskmaster = taskmaster
    yield
    close = getattr(repository, "close", None)
    if close:
        result = close()
        if hasattr(result, "__await__"):
            await result


app = FastAPI(
    title="NEMESIS Case Runtime",
    version="0.9.0",
    lifespan=lifespan,
    docs_url=None if settings.app_env == "production" else "/docs",
    openapi_url=None if settings.app_env == "production" else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "runtime": "nemesis",
        "environment": settings.app_env,
        "persistence": repository.__class__.__name__,
        "agent": classifier.__class__.__name__,
        "trace_engine": "deterministic_v2",
        "trace_max_depth": settings.trace_max_depth,
        "incident_discovery": "alchemy" if discovery else "unavailable",
        "historical_branch_continuation": "alchemy+rpc_verify" if settings.alchemy_api_key else "rpc",
        "realtime_movement_detection": "bitquery+rpc_verify" if settings.bitquery_access_token else "rpc",
        "authentication": "firebase" if (settings.firebase_project_id or settings.google_cloud_project) else "unconfigured",
        "enrichment": {
            "goplus": True,
            "chainabuse": bool(settings.chainabuse_api_key),
        },
    }


@app.post("/v1/cases", response_model=CaseResponse, status_code=201)
async def create_case(body: CaseCreate, user: dict = Depends(require_user)):
    try:
        response = await workflow.create_and_investigate(body)
        response.case.owner_user_id = user["sub"]
        response.case.owner_email = user.get("email")
        await repository.save(response.case)
        return response
    except IncidentNotFoundError as exc:
        raise HTTPException(422, str(exc)) from exc
    except DiscoveryUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except DiscoveryProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RpcProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/v1/me/cases")
async def my_cases(user: dict = Depends(require_user)):
    cases = await repository.list_by_owner(user["sub"])
    return [case.model_dump(mode="json") for case in cases]


@app.get("/v1/cases/{case_id}")
async def get_case(case_id: str, user: dict = Depends(require_user)):
    case = await owned_case(case_id, user)
    return case.model_dump(mode="json")


@app.get("/v1/cases/{case_id}/timeline")
async def get_timeline(case_id: str, user: dict = Depends(require_user)):
    await owned_case(case_id, user)
    if taskmaster is None:
        raise HTTPException(503, "monitoring runtime unavailable")
    return [e.model_dump(mode="json") for e in await taskmaster.repo.get_timeline(case_id)]


@app.get("/v1/cases/{case_id}/trace")
async def get_trace(case_id: str, user: dict = Depends(require_user)):
    await owned_case(case_id, user)
    if taskmaster is None:
        raise HTTPException(503, "tracing runtime unavailable")
    return await taskmaster.case_trace(case_id)


@app.post("/internal/monitoring/tick", dependencies=[Depends(require_internal)])
async def monitoring_tick():
    if taskmaster is None:
        raise HTTPException(503, "monitoring runtime unavailable")
    return {"rechecks_published": await taskmaster.schedule()}


@app.post("/internal/events/pubsub", dependencies=[Depends(require_internal)])
async def pubsub_event(request: Request):
    if taskmaster is None:
        raise HTTPException(503, "monitoring runtime unavailable")
    try:
        return await taskmaster.consume(decode_pubsub(await request.json()))
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
