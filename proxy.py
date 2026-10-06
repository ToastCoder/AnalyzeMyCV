import asyncio
import html
import json
import os
from urllib.parse import quote

from aiohttp import web, ClientSession, WSMsgType
from multidict import CIMultiDict

import clerk_auth

STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8001"))
PROXY_PORT = int(os.getenv("PROXY_PORT", "8000"))

# Matches Streamlit's server.maxUploadSize (8 MB) plus multipart overhead.
MAX_REQUEST_BYTES = 10 * 1024 * 1024

# Sign-in is Clerk (see clerk_auth.py). Identity reaches Streamlit only as X-Auth-*
# headers that this proxy sets after verifying the session; any copy a client sends
# is dropped. On App Service the proxy refuses to serve at all unless Clerk is configured.
ON_APP_SERVICE = bool(os.getenv("WEBSITE_SITE_NAME"))
IDENTITY_HEADER_PREFIX = "x-auth-"
SIGN_IN_PATH = "/auth/sign-in"
SIGN_OUT_PATH = "/auth/sign-out"
HEALTH_PATH = "/_stcore/health"

# Request headers that must not be copied verbatim to the upstream request.
HOP_BY_HOP_REQUEST_HEADERS = {"host", "connection", "transfer-encoding", "keep-alive", "upgrade"}
# The body is buffered and re-sent un-chunked, so these upstream values no longer apply.
# Content-Encoding is kept: bodies are forwarded still compressed (about 4x smaller for
# Streamlit's JS bundle), and the client's own Accept-Encoding is what Streamlit honours.
DROPPED_RESPONSE_HEADERS = {"transfer-encoding", "content-length", "connection"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Streamlit renders components in same-origin iframes, so allow 'self' only.
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "frame-ancestors 'self'",
}
if ON_APP_SERVICE:
    # App Service terminates TLS; local http runs must not send HSTS.
    SECURITY_HEADERS["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


def upstream_request_headers(request) -> CIMultiDict:
    """Client headers minus hop-by-hop ones and any forged identity; plus the verified identity."""
    headers = CIMultiDict()
    for k, v in request.headers.items():
        if k.lower() in HOP_BY_HOP_REQUEST_HEADERS or k.lower().startswith(IDENTITY_HEADER_PREFIX):
            continue
        headers.add(k, v)
    user = request.get("user")
    if user:
        headers.update(clerk_auth.identity_headers(user))
    return headers


async def proxy_websocket(request):
    target = f"http://127.0.0.1:{STREAMLIT_PORT}{request.path}"
    if request.query_string:
        target += "?" + request.query_string

    req_protocols = request.headers.get("Sec-WebSocket-Protocol", "")
    protocols = tuple(p.strip() for p in req_protocols.split(",")) if req_protocols else ()

    # Streamlit reads the signed-in user (st.context.headers) from the websocket handshake.
    identity = clerk_auth.identity_headers(request["user"]) if request.get("user") else {}

    ws_server = web.WebSocketResponse(autoping=True, protocols=protocols)
    await ws_server.prepare(request)

    session: ClientSession = request.app["client_session"]
    async with session.ws_connect(
        target, autoping=True, protocols=protocols, headers=identity
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
        response = web.Response(status=resp.status, headers=resp_headers, body=resp_body)
        if request.get("new_session_cookie"):
            set_session_cookie(response, request["new_session_cookie"], clerk_auth.SESSION_TTL_SECONDS)
        return response


def set_session_cookie(response, value: str, max_age: int):
    response.set_cookie(
        clerk_auth.SESSION_COOKIE, value, max_age=max_age, path="/",
        httponly=True, secure=ON_APP_SERVICE, samesite="Lax",
    )


def safe_redirect_target(target: str) -> str:
    """Only same-site relative paths; blocks open redirects such as //evil.com or /\\evil.com."""
    if target.startswith("/") and not target.startswith(("//", "/\\")) and not target.startswith("/auth/"):
        return target
    return "/"


AUTH_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AnalyzeMyCV</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#09090b;color:#f8fafc;font-family:ui-monospace,Menlo,Consolas,monospace}}
#msg{{text-align:center}}</style></head>
<body><div id="app"><p id="msg">{message}</p></div>
<script async crossorigin="anonymous" data-clerk-publishable-key="{publishable_key}"
 src="https://{host}/npm/@clerk/clerk-js@5/dist/clerk.browser.js"
 onload="run()"></script>
<script>
const REDIRECT = {redirect};
async function run() {{
  const msg = document.getElementById("msg");
  try {{
    await window.Clerk.load();
    {action}
  }} catch (e) {{
    msg.textContent = "Could not reach the sign-in service. Please reload.";
  }}
}}
</script></body></html>"""

SIGN_IN_ACTION = """
    // Guard against a redirect loop if the browser refuses to keep the session cookie.
    const tries = Number(sessionStorage.getItem("amcAuthTries") || 0);
    const finish = async () => {
      await window.Clerk.session.getToken();  // makes clerk-js write the __session cookie
      if (tries >= 3) {
        msg.textContent = "Signed in, but the browser blocked the session cookie. Allow cookies for this site.";
        return;
      }
      sessionStorage.setItem("amcAuthTries", String(tries + 1));
      location.replace(REDIRECT);
    };
    if (window.Clerk.session) { await finish(); return; }
    sessionStorage.removeItem("amcAuthTries");
    msg.remove();
    window.Clerk.mountSignIn(document.getElementById("app"));
    window.Clerk.addListener(({ session }) => { if (session) finish(); });
"""

SIGN_OUT_ACTION = """
    sessionStorage.removeItem("amcAuthTries");
    if (window.Clerk.session) await window.Clerk.signOut();
    location.replace("/");
"""


def auth_page(action: str, redirect: str, message: str) -> web.Response:
    body = AUTH_PAGE.format(
        publishable_key=html.escape(clerk_auth.PUBLISHABLE_KEY, quote=True),
        host=clerk_auth.FRONTEND_HOST,
        # "<" is escaped so the value can never close the surrounding <script>.
        redirect=json.dumps(redirect).replace("<", "\\u003c"),
        action=action,
        message=message,
    )
    return web.Response(text=body, content_type="text/html", headers={"Cache-Control": "no-store"})


async def sign_in_page(request):
    return auth_page(SIGN_IN_ACTION, safe_redirect_target(request.query.get("redirect", "/")), "Loading sign-in...")


async def sign_out_page(request):
    response = auth_page(SIGN_OUT_ACTION, "/", "Signing out...")
    set_session_cookie(response, "", 0)
    return response


@web.middleware
async def auth_middleware(request, handler):
    request["user"] = None
    path = request.path
    if path == HEALTH_PATH:  # platform health probes
        return await handler(request)
    if not clerk_auth.ENABLED:
        if ON_APP_SERVICE or clerk_auth.CONFIGURED:
            return web.Response(status=503, text="Authentication is not configured correctly.")
        return await handler(request)  # local development: Streamlit falls back to LOCAL_DEV_USER_EMAIL
    if path in (SIGN_IN_PATH, SIGN_OUT_PATH):
        return await handler(request)

    user, new_cookie = await clerk_auth.authenticate(request.cookies, request.app["client_session"])
    if user:
        request["user"] = user
        request["new_session_cookie"] = new_cookie
        return await handler(request)

    wants_page = request.method == "GET" and "text/html" in request.headers.get("Accept", "")
    if wants_page and request.headers.get("Upgrade", "").lower() != "websocket":
        target = path + ("?" + request.query_string if request.query_string else "")
        return web.HTTPFound(f"{SIGN_IN_PATH}?redirect={quote(target, safe='')}", headers={"Cache-Control": "no-store"})
    return web.Response(status=401, text="Authentication required.")


async def handle_catchall(request):
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await proxy_websocket(request)
    return await proxy_http(request)


async def create_client_session(app):
    app["client_session"] = ClientSession(auto_decompress=False)
    yield
    await app["client_session"].close()


app = web.Application(client_max_size=MAX_REQUEST_BYTES, middlewares=[auth_middleware])
app.cleanup_ctx.append(create_client_session)
app.router.add_get(SIGN_IN_PATH, sign_in_page)
app.router.add_get(SIGN_OUT_PATH, sign_out_page)
app.router.add_route("*", "/{path_info:.*}", handle_catchall)

if __name__ == "__main__":
    print(f"Proxy: Starting on port {PROXY_PORT}, forwarding to Streamlit on {STREAMLIT_PORT}")
    print(f"Proxy: Clerk authentication enabled: {clerk_auth.ENABLED}")
    if clerk_auth.CONFIGURED and not clerk_auth.ENABLED:
        print("Proxy: WARNING: CLERK_PUBLISHABLE_KEY is invalid or JWT_SECRET is shorter than 32 characters; refusing all requests")
    web.run_app(app, host="0.0.0.0", port=PROXY_PORT)
