"""
Authentication Middleware for Nexus Scraper.
Verifies the presence and validity of the Bearer Token in the Authorization header.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from nexus.config import settings


class AuthMiddleware(BaseHTTPMiddleware):
    """
    HTTP middleware that checks for a valid Bearer token in incoming requests.
    Public endpoints such as '/health', '/docs', '/redoc', and '/openapi.json' are bypassed.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Define bypass endpoints
        bypass_paths = {"/health", "/docs", "/redoc", "/openapi.json"}
        if request.url.path in bypass_paths or request.url.path.startswith("/docs"):
            return await call_next(request)

        # Check authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing Authorization header"}
            )

        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid Authorization header format. Must be 'Bearer <token>'"}
            )

        token = auth_header[7:].strip()
        if token != settings.api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized. Invalid Bearer Token"}
            )

        return await call_next(request)
