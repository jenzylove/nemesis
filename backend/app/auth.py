from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings

settings = get_settings()
user_bearer = HTTPBearer(auto_error=False)


async def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(user_bearer),
) -> dict:
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
