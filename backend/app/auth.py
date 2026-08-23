from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .models import CaseCreate

settings = get_settings()
user_bearer = HTTPBearer(auto_error=False)


def verify_user_credentials(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "sign in required")
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token

        claims = id_token.verify_firebase_token(
            credentials.credentials,
            GoogleRequest(),
            audience=settings.firebase_project_id or settings.google_cloud_project,
        )
    except Exception as exc:
        raise HTTPException(401, "invalid user identity token") from exc
    if not claims or not claims.get("sub"):
        raise HTTPException(401, "invalid user identity token")
    return claims


async def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(user_bearer),
) -> dict:
    return verify_user_credentials(credentials)


async def require_case_user(
    body: CaseCreate,
    credentials: HTTPAuthorizationCredentials | None = Depends(user_bearer),
) -> dict:
    # Making the request model part of this dependency preserves FastAPI's
    # schema validation contract: malformed case payloads return 422 before
    # authentication is evaluated, while valid investigations still require
    # a Firebase bearer token.
    _ = body
    return verify_user_credentials(credentials)
