import asyncio
import os

from aiohttp import web, ClientSession, WSMsgType

STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8001"))
PROXY_PORT = int(os.getenv("PROXY_PORT", "8000"))

CALLBACK_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Confirming account...</title></head>
<body>
<p>Confirming your account, please wait...</p>
<script>
(function () {
  var hash = window.location.hash;
  if (hash && hash.indexOf("access_token=") !== -1) {
    var params = new URLSearchParams(hash.replace("#", "?"));
    var token = params.get("access_token");
    if (token) {
      window.location.href = "/?confirm_token=" + encodeURIComponent(token);
      return;
    }
  }
  window.location.href = "/";
})();
</script>
</body>
</html>"""


async def handle_callback(request):
    return web.Response(text=CALLBACK_HTML, content_type="text/html")


async def proxy_websocket(request):
    target = f"http://127.0.0.1:{STREAMLIT_PORT}{request.path}"
    if request.query_string:
        target += "?" + request.query_string

    ws_server = web.WebSocketResponse(autoping=True)
    await ws_server.prepare(request)

    async with ClientSession() as session:
        async with session.ws_connect(target, autoping=True) as ws_client:

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
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host",)}

    async with ClientSession() as session:
        body = await request.read()
        async with session.request(
            request.method, target, headers=headers, data=body, allow_redirects=False
        ) as resp:
            resp_headers = {
                k: v
                for k, v in resp.headers.items()
                if k.lower() not in ("transfer-encoding", "content-encoding")
            }
            resp_body = await resp.read()
            return web.Response(status=resp.status, headers=resp_headers, body=resp_body)


async def handle_catchall(request):
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await proxy_websocket(request)
    return await proxy_http(request)


app = web.Application()
app.router.add_get("/auth/callback", handle_callback)
app.router.add_route("*", "/{path_info:.*}", handle_catchall)

if __name__ == "__main__":
    print(f"Proxy: Starting on port {PROXY_PORT}, forwarding to Streamlit on {STREAMLIT_PORT}")
    web.run_app(app, host="0.0.0.0", port=PROXY_PORT)
