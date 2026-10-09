import asyncio
import html
import json
import os
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from aiohttp import web, ClientSession, WSMsgType
from multidict import CIMultiDict
from yarl import URL

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
# Extra hostnames (comma-separated) accepted in the Origin header, for hosting that rewrites Host.
EXTRA_ALLOWED_HOSTS = {h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()}
PUBLIC_STATIC_PREFIX = "/static/"
# Inter (SIL OFL) is self-hosted: served here, under /auth/ so the sign-in page can use it
# before login, and cached for a year. Rename the file if it is ever replaced.
FONT_PATH = "/auth/fonts/InterVariable.woff2"
FONT_FILE = Path(__file__).resolve().parent / "assets" / "fonts" / "InterVariable.woff2"
FONT_STACK = 'Inter, -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, "Segoe UI", Roboto, sans-serif'

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


# Session cookies are for this proxy only; Streamlit (and any code it runs) never needs them.
PRIVATE_COOKIE_PREFIXES = (clerk_auth.SESSION_COOKIE, "__session", "__client", "__clerk", "__refresh")


def strip_private_cookies(cookie_header: str) -> str:
    kept = [c for c in cookie_header.split(";") if not c.strip().startswith(PRIVATE_COOKIE_PREFIXES)]
    return ";".join(kept).strip()


def upstream_request_headers(request) -> CIMultiDict:
    """Client headers minus hop-by-hop ones and any forged identity; plus the verified identity."""
    headers = CIMultiDict()
    for k, v in request.headers.items():
        if k.lower() in HOP_BY_HOP_REQUEST_HEADERS or k.lower().startswith(IDENTITY_HEADER_PREFIX):
            continue
        if k.lower() == "cookie":
            v = strip_private_cookies(v)
            if not v:
                continue
        headers.add(k, v)
    user = request.get("user")
    if user:
        headers.update(clerk_auth.identity_headers(user))
    return headers


def upstream_url(request) -> URL:
    """The request's own encoded path and query, byte for byte. Rebuilding it from the decoded
    path would let `..` or an encoded `/` change which upstream route the request reaches
    after the auth decision was made on a different-looking path."""
    raw = request.rel_url.raw_path
    if request.rel_url.raw_query_string:
        raw += "?" + request.rel_url.raw_query_string
    return URL(f"http://127.0.0.1:{STREAMLIT_PORT}{raw}", encoded=True)


async def proxy_websocket(request):
    target = upstream_url(request)

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
    target = upstream_url(request)
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


async def font_file(request):
    return web.FileResponse(
        FONT_FILE, headers={"Content-Type": "font/woff2", "Cache-Control": "public, max-age=31536000, immutable"}
    )


AUTH_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AnalyzeMyCV</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>@font-face{{font-family:Inter;src:url("{font_path}") format("woff2");font-weight:100 900;font-display:swap}}
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#09090b;color:#f8fafc;font-family:{font_stack}}}
#msg{{text-align:center}}</style></head>
<body><div id="app"><p id="msg">{message}</p></div>
<script async crossorigin="anonymous" data-clerk-publishable-key="{publishable_key}"
 src="https://{host}/npm/@clerk/clerk-js@5/dist/clerk.browser.js"
 onload="run()"></script>
<script>
const REDIRECT = {redirect};
const FONT_STACK = {font_stack_js};
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
    window.Clerk.mountSignIn(document.getElementById("app"), { appearance: { variables: { fontFamily: FONT_STACK } } });
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
        font_path=FONT_PATH,
        font_stack=FONT_STACK.replace('"', "&quot;"),
        font_stack_js=json.dumps(FONT_STACK),
    )
    return web.Response(text=body, content_type="text/html", headers={"Cache-Control": "no-store"})


async def sign_in_page(request):
    return auth_page(SIGN_IN_ACTION, safe_redirect_target(request.query.get("redirect", "/")), "Loading sign-in...")


async def sign_out_page(request):
    response = auth_page(SIGN_OUT_ACTION, "/", "Signing out...")
    set_session_cookie(response, "", 0)
    return response


@web.middleware
async def security_headers_middleware(request, handler):
    """Outermost, so every response (proxied or generated here, including errors and redirects) gets them."""
    try:
        response = await handler(request)
    except web.HTTPException as exc:  # e.g. aiohttp's own 404/405; turned into a normal response
        response = web.Response(status=exc.status, text=exc.text or exc.reason)
        if "Location" in exc.headers:
            response.headers["Location"] = exc.headers["Location"]
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


def is_suspicious_path(request) -> bool:
    """Paths that could be read differently by this proxy and by Streamlit: encoded slashes,
    backslashes, double-encoding, NULs, and dot segments (which the auth rules must never see
    as a public-looking prefix such as /static/../_stcore/...)."""
    raw = request.rel_url.raw_path
    lowered = raw.lower()
    if any(token in lowered for token in ("%2f", "%5c", "%00", "%25")) or "\\" in raw:
        return True
    return any(segment in ("..", ".") for segment in unquote(raw).split("/"))


def origin_matches(request) -> bool:
    """Browsers send Origin on WebSocket handshakes and cross-site writes. If it names another
    site, refuse: cookie-authenticated requests must come from this app's own pages."""
    origin = request.headers.get("Origin")
    if not origin or origin == "null":
        return origin is None  # "null" (sandboxed/opaque origins) is never ours
    allowed = {request.host.lower(), *EXTRA_ALLOWED_HOSTS}
    forwarded = request.headers.get("X-Forwarded-Host", "").split(",")[0].strip().lower()
    if forwarded:
        allowed.add(forwarded)
    netloc = urlsplit(origin).netloc.lower()
    if netloc in allowed:
        return True
    # Hostnames only (no cookies, no content): enough to diagnose a proxy that rewrites Host.
    print(f"Proxy: refused cross-origin request: origin={netloc} host={request.host.lower()} (set ALLOWED_HOSTS to allow more)")
    return False


@web.middleware
async def request_guard_middleware(request, handler):
    if is_suspicious_path(request):
        return web.Response(status=400, text="Bad request.")
    is_ws = request.headers.get("Upgrade", "").lower() == "websocket"
    if (is_ws or request.method not in ("GET", "HEAD", "OPTIONS")) and not origin_matches(request):
        return web.Response(status=403, text="Cross-origin request refused.")
    return await handler(request)


@web.middleware
async def auth_middleware(request, handler):
    request["user"] = None
    path = request.path
    # Health probes and Streamlit's frontend bundle: identical for everyone, no user data. The bundle
    # must stay public because Streamlit lazy-loads widget scripts mid-session, possibly after the
    # session cookie has expired, and a 401 there breaks the widget ("Importing a module script failed").
    if request.method in ("GET", "HEAD") and (path == HEALTH_PATH or path.startswith(PUBLIC_STATIC_PREFIX)):
        return await handler(request)
    if not clerk_auth.ENABLED:
        if ON_APP_SERVICE or clerk_auth.CONFIGURED:
            return web.Response(status=503, text="Authentication is not configured correctly.")
        return await handler(request)  # local development: Streamlit falls back to LOCAL_DEV_USER_EMAIL
    if path in (SIGN_IN_PATH, SIGN_OUT_PATH, FONT_PATH):
        return await handler(request)

    user, new_cookie = await clerk_auth.authenticate(request.cookies, request.app["client_session"])
    if user:
        request["user"] = user
        request["new_session_cookie"] = new_cookie
        return await handler(request)

    wants_page = request.method == "GET" and "text/html" in request.headers.get("Accept", "")
    if wants_page and request.headers.get("Upgrade", "").lower() != "websocket":
        target = path + ("?" + request.query_string if request.query_string else "")
        return web.Response(
            status=302,
            headers={"Location": f"{SIGN_IN_PATH}?redirect={quote(target, safe='')}", "Cache-Control": "no-store"},
        )
    return web.Response(status=401, text="Authentication required.")


async def handle_catchall(request):
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await proxy_websocket(request)
    return await proxy_http(request)


async def create_client_session(app):
    app["client_session"] = ClientSession(auto_decompress=False)
    yield
    await app["client_session"].close()


def make_app() -> web.Application:
    app = web.Application(client_max_size=MAX_REQUEST_BYTES, middlewares=[security_headers_middleware, request_guard_middleware, auth_middleware])
    app.cleanup_ctx.append(create_client_session)
    app.router.add_get(SIGN_IN_PATH, sign_in_page)
    app.router.add_get(SIGN_OUT_PATH, sign_out_page)
    app.router.add_get(FONT_PATH, font_file)
    app.router.add_route("*", "/{path_info:.*}", handle_catchall)
    return app


app = make_app()

if __name__ == "__main__":
    print(f"Proxy: Starting on port {PROXY_PORT}, forwarding to Streamlit on {STREAMLIT_PORT}")
    print(f"Proxy: Clerk authentication enabled: {clerk_auth.ENABLED}")
    for warning in clerk_auth.configuration_warnings():
        print(f"Proxy: WARNING: {warning}")
    if clerk_auth.CONFIGURED and not clerk_auth.ENABLED:
        print("Proxy: WARNING: CLERK_PUBLISHABLE_KEY is invalid or JWT_SECRET is shorter than 32 characters; refusing all requests")
    web.run_app(app, host="0.0.0.0", port=PROXY_PORT)
