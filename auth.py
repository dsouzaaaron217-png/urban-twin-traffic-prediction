import secrets
from fastapi import Header, HTTPException, status
from settings import settings

def get_role(x_api_key: str = Header(None)) -> str:
    """Role lookup based on X-API-Key header.
    - If x_api_key is None (anonymous request), role is 'viewer'.
    - If x_api_key is provided:
        - If API_KEY is unset or invalid key provided, raise 401 Unauthorized (never silently downgrade to viewer).
        - If valid admin key matches settings.api_key, role is 'admin'.
    """
    if x_api_key is None:
        return "viewer"

    server_key = settings.api_key
    if not server_key or not secrets.compare_digest(x_api_key, server_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or unrecognized API key.",
        )
    return "admin"

def require_admin(x_api_key: str = Header(None)) -> str:
    """Require admin role for protected endpoints.
    - If API_KEY is not configured on the server, reject with 503 Service Unavailable (configuration error).
    - If x_api_key is missing or invalid, reject with 401 Unauthorized.
    - If valid, grant 'admin'.
    """
    server_key = settings.api_key
    if not server_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured on the server.",
        )

    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key header (X-API-Key) is required for admin access.",
        )

    if not secrets.compare_digest(x_api_key, server_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    return "admin"
