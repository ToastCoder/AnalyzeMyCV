import asyncio
import os

from aiohttp import web, ClientSession, WSMsgType
from multidict import CIMultiDict

STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8001"))
PROXY_PORT = int(os.getenv("PROXY_PORT", "8000"))

# Matches Streamlit's server.maxUploadSize (8 MB) plus multipart overhead.
MAX_REQUEST_BYTES = 10 * 1024 * 1024

# App Service sets WEBSITE_AUTH_ENABLED=True when Authentication (Easy Auth) is on.
# Easy Auth then strips client-supplied identity headers and injects its own, so
# they can be trusted. When it is off, anyone could forge them, so they're dropped.
EASY_AUTH_ENABLED = os.getenv("WEBSITE_AUTH_ENABLED", "").strip().lower() == "true"
IDENTITY_HEADER_PREFIXES = ("x-ms-client-principal", "x-ms-token-")

# Request headers that must not be copied verbatim to the upstream request.
HOP_BY_HOP_REQUEST_HEADERS = {"host", "connection", "transfer-encoding", "keep-alive", "upgrade"}
# The body is re-sent decoded and un-chunked, so these upstream values no longer apply.
DROPPED_RESPONSE_HEADERS = {"transfer-encoding", "content-encoding", "content-length", "connection"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Streamlit renders components in same-origin iframes, so allow 'self' only.
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "frame-ancestors 'self'",
}
if EASY_AUTH_ENABLED:
    # Only on App Service, which terminates TLS; local http runs must not send HSTS.
    SECURITY_HEADERS["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


def is_identity_header(name: str) -> bool:
    return name.lower().startswith(IDENTITY_HEADER_PREFIXES)


def upstream_request_headers(request) -> CIMultiDict:
    headers = CIMultiDict()
    for k, v in request.headers.items():
        if k.lower() in HOP_BY_HOP_REQUEST_HEADERS:
            continue
        if is_identity_header(k) and not EASY_AUTH_ENABLED:
            continue
        headers.add(k, v)
    return headers


async def proxy_websocket(request):
    target = f"http://127.0.0.1:{STREAMLIT_PORT}{request.path}"
    if request.query_string:
        target += "?" + request.query_string

    req_protocols = request.headers.get("Sec-WebSocket-Protocol", "")
    protocols = tuple(p.strip() for p in req_protocols.split(",")) if req_protocols else ()

    # Streamlit reads the signed-in user (st.context.headers) from the websocket
    # handshake, so Easy Auth's identity headers must be forwarded here too.
    identity_headers = (
        {k: v for k, v in request.headers.items() if is_identity_header(k)}
        if EASY_AUTH_ENABLED else {}
    )

    ws_server = web.WebSocketResponse(autoping=True, protocols=protocols)
    await ws_server.prepare(request)

    session: ClientSession = request.app["client_session"]
    async with session.ws_connect(
        target, autoping=True, protocols=protocols, headers=identity_headers
    ) as ws_client:

        async def forward(src, dst):
            try:
                async for msg in src:
                    if msg.type == WSMsgType.TEXT:
                        await dst.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await dst.send_bytes(msg.data)
                    elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break
            except Exception:
                pass

        await asyncio.gather(forward(ws_server, ws_client), forward(ws_client, ws_server))

    return ws_server


async def proxy_http(request):
    path = request.path
    if request.query_string:
        path += "?" + request.query_string

    target = f"http://127.0.0.1:{STREAMLIT_PORT}{path}"
    body = await request.read()

    session: ClientSession = request.app["client_session"]
    async with session.request(
        request.method, target, headers=upstream_request_headers(request), data=body, allow_redirects=False
    ) as resp:
        # CIMultiDict keeps repeated headers such as multiple Set-Cookie lines;
        # a plain dict would silently keep only the last one.
        resp_headers = CIMultiDict(
            (k, v) for k, v in resp.headers.items() if k.lower() not in DROPPED_RESPONSE_HEADERS
        )
        for k, v in SECURITY_HEADERS.items():
            resp_headers.setdefault(k, v)
        resp_body = await resp.read()
        return web.Response(status=resp.status, headers=resp_headers, body=resp_body)


async def handle_catchall(request):
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await proxy_websocket(request)
    return await proxy_http(request)


async def create_client_session(app):
    app["client_session"] = ClientSession(auto_decompress=True)
    yield
    await app["client_session"].close()


app = web.Application(client_max_size=MAX_REQUEST_BYTES)
app.cleanup_ctx.append(create_client_session)
app.router.add_route("*", "/{path_info:.*}", handle_catchall)

if __name__ == "__main__":
    print(f"Proxy: Starting on port {PROXY_PORT}, forwarding to Streamlit on {STREAMLIT_PORT}")
    print(f"Proxy: App Service Authentication enabled: {EASY_AUTH_ENABLED}")
    web.run_app(app, host="0.0.0.0", port=PROXY_PORT)
