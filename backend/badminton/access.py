"""Single-user HTTP authentication and bounded incoming request bodies."""

import base64
import hmac
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.responses import Response


class AccessMiddleware:
    def __init__(self, app, username=None, password=None, max_bytes=2 * 1024**3):
        if bool(username) != bool(password):
            raise ValueError("Set both BADMINTON_USERNAME and BADMINTON_PASSWORD")
        self.app = app
        self.credential = (
            base64.b64encode(f"{username}:{password}".encode()).decode()
            if username and password
            else None
        )
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        if self.credential and scope["path"] != "/api/health":
            scheme, _, token = headers.get("authorization", "").partition(" ")
            if scheme.lower() != "basic" or not hmac.compare_digest(
                token.encode(), self.credential.encode()
            ):
                return await Response(
                    "Authentication required",
                    status_code=401,
                    headers={
                        "WWW-Authenticate": 'Basic realm="Court Notes", charset="UTF-8"'
                    },
                )(scope, receive, send)
        origin = headers.get("origin")
        if scope["method"] not in ("GET", "HEAD", "OPTIONS") and origin:
            try:
                same_host = (
                    urlsplit(origin).netloc.lower() == headers.get("host", "").lower()
                )
            except ValueError:
                same_host = False
            if not same_host:
                return await Response(
                    "Cross-site changes are not allowed", status_code=403
                )(scope, receive, send)
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            return await Response("Invalid Content-Length", status_code=400)(
                scope, receive, send
            )
        limit = self.max_bytes + 1024**2
        if length < 0 or length > limit:
            return await Response(
                "Upload exceeds the configured size limit", status_code=413
            )(scope, receive, send)
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > limit:
                raise HTTPException(413, "Upload exceeds the configured size limit")
            return message

        await self.app(scope, bounded_receive, send)
