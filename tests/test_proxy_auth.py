# AnalyzeMyCV
# tests/test_proxy_auth.py
"""Clerk session handling in proxy.py, with a fake upstream and a locally generated Clerk key."""

import gzip
import os
import json
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest import mock

import jwt
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestServer
from cryptography.hazmat.primitives.asymmetric import rsa

# A developer's .env.local may hold production Clerk keys; tests must never pick them up.
for _name in ("CLERK_SECRET_KEY", "CLERK_PUBLISHABLE_KEY", "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "CLERK_AUTHORIZED_PARTIES"):
    os.environ[_name] = ""

import clerk_auth
import proxy

SECRET = "s" * 40
HOST = "test-app.clerk.accounts.dev"
ISSUER = f"https://{HOST}"
PAGE = {"Accept": "text/html"}
CLERK_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def clerk_token(key=CLERK_KEY, sub="user_123", iss=ISSUER, exp_in=60, **extra):
    now = int(time.time())
    claims = {"sub": sub, "iss": iss, "iat": now, "exp": now + exp_in, **extra}
    return jwt.encode(claims, key, algorithm="RS256")


class CountingJWKS:
    """Stands in for Clerk's key endpoint and counts how often it is asked."""

    def __init__(self):
        self.calls = 0

    def get_signing_keys(self, refresh=False):
        self.calls += 1
        return []


class ProxyAuthTest(AioHTTPTestCase):
    async def get_application(self):
        async def echo(request):
            if request.path == "/gz":
                return web.Response(body=gzip.compress(b"x" * 10_000), headers={"Content-Encoding": "gzip"})
            return web.json_response({k: v for k, v in request.headers.items() if k.lower().startswith("x-auth-")})

        upstream = web.Application()
        upstream.router.add_route("*", "/{p:.*}", echo)
        self.upstream = TestServer(upstream)
        await self.upstream.start_server()

        patches = [
            mock.patch.object(proxy, "STREAMLIT_PORT", self.upstream.port),
            mock.patch.object(clerk_auth, "ENABLED", True),
            mock.patch.object(clerk_auth, "JWT_SECRET", SECRET),
            mock.patch.object(clerk_auth, "ISSUER", ISSUER),
            mock.patch.object(clerk_auth, "FRONTEND_HOST", HOST),
            mock.patch.object(clerk_auth, "SECRET_KEY", ""),
            mock.patch.object(clerk_auth, "AUTHORIZED_PARTIES", set()),
            mock.patch.object(clerk_auth, "_signing_key", lambda kid: CLERK_KEY.public_key()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addAsyncCleanup(self.upstream.close)
        # A fresh app per test: aiohttp applications can't be reused across event loops.
        return proxy.make_app()

    async def test_anonymous_page_redirects_to_sign_in(self):
        resp = await self.client.get("/some/page?x=1", headers=PAGE, allow_redirects=False)
        self.assertEqual(resp.status, 302)
        location = urlsplit(resp.headers["Location"])
        self.assertEqual(location.path, "/auth/sign-in")
        self.assertEqual(parse_qs(location.query), {"redirect": ["/some/page?x=1"]})

    async def test_anonymous_non_page_request_is_401(self):
        resp = await self.client.get("/_stcore/stream", allow_redirects=False)
        self.assertEqual(resp.status, 401)

    async def test_websocket_upgrade_without_session_is_401(self):
        resp = await self.client.get(
            "/_stcore/stream",
            headers={**PAGE, "Upgrade": "websocket", "Connection": "Upgrade"},
            allow_redirects=False,
        )
        self.assertEqual(resp.status, 401)

    async def test_forged_identity_headers_do_not_authenticate(self):
        resp = await self.client.get(
            "/", headers={**PAGE, "X-Auth-User-Id": "admin"}, allow_redirects=False
        )
        self.assertEqual(resp.status, 302)

    async def test_valid_clerk_session_reaches_upstream_and_sets_own_cookie(self):
        resp = await self.client.get(
            "/", headers={"X-Auth-User-Id": "forged", "X-Auth-Email": "x@evil.com"},
            cookies={"__session": clerk_token()},
        )
        self.assertEqual(resp.status, 200)
        # Upstream sees the verified id, not the forged one, and no forged email.
        self.assertEqual(await resp.json(), {"X-Auth-User-Id": "user_123"})
        cookie = resp.cookies["amc_session"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")

        # The proxy's own cookie works without the (60-second) Clerk token.
        resp = await self.client.get("/", cookies={"amc_session": cookie.value})
        self.assertEqual(resp.status, 200)
        self.assertEqual(await resp.json(), {"X-Auth-User-Id": "user_123"})

    async def test_name_and_email_claims_reach_upstream_percent_encoded(self):
        token = clerk_token(name="Jane Q Public \u00e9", email="jane@example.com")
        resp = await self.client.get("/", cookies={"__session": token})
        self.assertEqual(await resp.json(), {
            "X-Auth-User-Id": "user_123",
            "X-Auth-Email": "jane%40example.com",
            "X-Auth-Name": "Jane%20Q%20Public%20%C3%A9",
        })

    async def test_rejects_bad_clerk_tokens(self):
        bad = {
            "expired": clerk_token(exp_in=-60),
            "wrong issuer": clerk_token(iss="https://evil.example"),
            "wrong key": clerk_token(key=OTHER_KEY),
            "garbage": "not-a-jwt",
        }
        for label, token in bad.items():
            with self.subTest(label):
                resp = await self.client.get("/", headers=PAGE, cookies={"__session": token}, allow_redirects=False)
                self.assertEqual(resp.status, 302)

    async def test_authorized_party_is_enforced_when_configured(self):
        with mock.patch.object(clerk_auth, "AUTHORIZED_PARTIES", {"https://app.example.com"}):
            for azp, expected in (("https://app.example.com", 200), ("https://evil.example", 302)):
                with self.subTest(azp):
                    self.client.session.cookie_jar.clear()  # drop amc_session from the previous subtest
                    resp = await self.client.get(
                        "/", headers=PAGE, cookies={"__session": clerk_token(azp=azp)}, allow_redirects=False
                    )
                    self.assertEqual(resp.status, expected)

    async def test_session_cookie_signed_with_other_secret_is_rejected(self):
        now = int(time.time())
        forged = jwt.encode(
            {"sub": "x", "iss": clerk_auth.SESSION_ISSUER, "aud": clerk_auth.SESSION_AUDIENCE, "iat": now, "exp": now + 60},
            "z" * 40, algorithm="HS256",
        )
        resp = await self.client.get("/", headers=PAGE, cookies={"amc_session": forged}, allow_redirects=False)
        self.assertEqual(resp.status, 302)

    async def test_compressed_responses_are_forwarded_without_decompressing(self):
        resp = await self.client.get("/gz", cookies={"__session": clerk_token()}, auto_decompress=False)
        self.assertEqual(resp.headers["Content-Encoding"], "gzip")
        self.assertEqual(gzip.decompress(await resp.read()), b"x" * 10_000)
        self.assertLess(int(resp.headers["Content-Length"]), 1000)

    async def test_every_response_carries_security_headers(self):
        cases = (
            await self.client.get("/", headers=PAGE, allow_redirects=False),   # 302 generated here
            await self.client.get("/_stcore/stream", allow_redirects=False),   # 401 generated here
            await self.client.get("/auth/sign-in"),                            # page generated here
            await self.client.get("/", cookies={"__session": clerk_token()}),  # proxied
        )
        for resp in cases:
            with self.subTest(status=resp.status):
                self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(resp.headers["X-Frame-Options"], "SAMEORIGIN")

    async def test_font_is_public_cacheable_and_pages_use_it(self):
        resp = await self.client.get("/auth/fonts/InterVariable.woff2")  # no session
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers["Content-Type"], "font/woff2")
        self.assertIn("immutable", resp.headers["Cache-Control"])
        self.assertEqual((await resp.read())[:4], b"wOF2")
        page = await (await self.client.get("/auth/sign-in")).text()
        self.assertIn('src:url("/auth/fonts/InterVariable.woff2")', page)

    async def test_other_auth_paths_are_not_public_files(self):
        resp = await self.client.get("/auth/fonts/../../clerk_auth.py", headers=PAGE, allow_redirects=False)
        self.assertIn(resp.status, (302, 401, 404))

    async def test_streamlit_static_bundle_is_public_but_other_paths_are_not(self):
        self.assertEqual((await self.client.get("/static/js/Metric.abc.js")).status, 200)
        for path in ("/media/abc.md", "/_stcore/upload_file/x/y", "/staticfoo", "/app/static/secret"):
            with self.subTest(path):
                self.assertEqual((await self.client.get(path, allow_redirects=False)).status, 401)

    async def test_health_is_public(self):
        resp = await self.client.get("/_stcore/health")
        self.assertEqual(resp.status, 200)

    async def test_sign_in_page_blocks_open_redirects(self):
        for target, expected in (("//evil.com", '"/"'), ("/\\evil.com", '"/"'), ("https://evil.com", '"/"'),
                                 ("/auth/sign-in", '"/"'), ("/ok?a=1", '"/ok?a=1"')):
            with self.subTest(target):
                resp = await self.client.get("/auth/sign-in", params={"redirect": target})
                self.assertEqual(resp.status, 200)
                self.assertIn(f"const REDIRECT = {expected};", await resp.text())

    async def test_sign_in_page_cannot_break_out_of_script(self):
        resp = await self.client.get("/auth/sign-in", params={"redirect": "/</script><script>alert(1)"})
        self.assertNotIn("</script><script>alert", await resp.text())

    async def test_sign_out_clears_session_cookie(self):
        resp = await self.client.get("/auth/sign-out")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.cookies["amc_session"].value, "")

    async def test_refuses_to_serve_on_app_service_without_clerk(self):
        with mock.patch.object(clerk_auth, "ENABLED", False), mock.patch.object(proxy, "ON_APP_SERVICE", True):
            resp = await self.client.get("/", headers=PAGE, allow_redirects=False)
            self.assertEqual(resp.status, 503)

    async def test_refuses_to_serve_when_clerk_key_set_but_config_invalid(self):
        with mock.patch.object(clerk_auth, "ENABLED", False), mock.patch.object(clerk_auth, "CONFIGURED", True), \
                mock.patch.object(proxy, "ON_APP_SERVICE", False):
            resp = await self.client.get("/", headers=PAGE, allow_redirects=False)
            self.assertEqual(resp.status, 503)

    async def test_local_dev_without_clerk_passes_through_without_identity(self):
        with mock.patch.object(clerk_auth, "ENABLED", False), mock.patch.object(clerk_auth, "CONFIGURED", False), \
                mock.patch.object(proxy, "ON_APP_SERVICE", False):
            resp = await self.client.get("/", headers={"X-Auth-User-Id": "forged"})
            self.assertEqual(resp.status, 200)
            self.assertEqual(await resp.json(), {})


class ProxyHardeningTest(AioHTTPTestCase):
    """The /static/ bypass, cross-origin refusal, cookie stripping and JWKS refetch limits."""

    async def get_application(self):
        async def echo(request):
            return web.json_response({"path": request.raw_path, "cookie": request.headers.get("Cookie", "")})

        upstream = web.Application()
        upstream.router.add_route("*", "/{p:.*}", echo)
        self.upstream = TestServer(upstream)
        await self.upstream.start_server()
        for p in (
            mock.patch.object(proxy, "STREAMLIT_PORT", self.upstream.port),
            mock.patch.object(clerk_auth, "ENABLED", True),
            mock.patch.object(clerk_auth, "JWT_SECRET", SECRET),
            mock.patch.object(clerk_auth, "ISSUER", ISSUER),
            mock.patch.object(clerk_auth, "_signing_key", lambda kid: CLERK_KEY.public_key()),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.addAsyncCleanup(self.upstream.close)
        return proxy.make_app()

    async def raw_get(self, path, headers=None):
        """Send the path exactly as written; the client library would otherwise normalize it."""
        import aiohttp
        from yarl import URL
        url = URL(f"http://{self.server.host}:{self.server.port}{path}", encoded=True)
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers or {}, allow_redirects=False) as r:
                return r.status, await r.text()

    async def test_dot_segments_cannot_borrow_the_public_static_prefix(self):
        for path in ("/static/../_stcore/host-config", "/static/%2e%2e/_stcore/host-config",
                     "/static/..%2f_stcore/host-config", "/static/./../media/x", "/static/%2E%2E/x",
                     "/static%5c..%5cmedia", "/static/%252e%252e/x", "/static/x%00"):
            with self.subTest(path):
                status, _ = await self.raw_get(path)
                self.assertEqual(status, 400)

    async def test_legitimate_static_and_health_stay_public_for_reads_only(self):
        status, _ = await self.raw_get("/static/js/index.abc123.js")
        self.assertEqual(status, 200)
        post = await self.client.post("/static/js/index.abc123.js")
        self.assertEqual(post.status, 401)
        self.assertEqual((await self.client.post("/_stcore/health")).status, 401)

    async def test_upstream_receives_the_original_encoded_path(self):
        status, body = await self.raw_get("/static/a%20b.js?x=%3F&y=1")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["path"], "/static/a%20b.js?x=%3F&y=1")

    async def test_cross_origin_writes_and_websockets_are_refused(self):
        cookies = {"__session": clerk_token()}
        host = f"{self.server.host}:{self.server.port}"
        evil = await self.client.post("/_stcore/upload_file/x", headers={"Origin": "https://evil.example"}, cookies=cookies)
        self.assertEqual(evil.status, 403)
        null = await self.client.post("/_stcore/upload_file/x", headers={"Origin": "null"}, cookies=cookies)
        self.assertEqual(null.status, 403)
        ws = await self.client.get("/_stcore/stream", headers={"Origin": "https://evil.example", "Upgrade": "websocket",
                                                              "Connection": "Upgrade"}, cookies=cookies)
        self.assertEqual(ws.status, 403)
        # Same-origin and header-less (non-browser) requests are fine.
        same = await self.client.post("/_stcore/upload_file/x", headers={"Origin": f"http://{host}"}, cookies=cookies)
        self.assertEqual(same.status, 200)
        self.assertEqual((await self.client.post("/_stcore/upload_file/x", cookies=cookies)).status, 200)
        # Plain GETs from other origins are unaffected (they are just navigations).
        self.assertEqual((await self.client.get("/", headers={"Origin": "https://evil.example"}, cookies=cookies)).status, 200)

    async def test_allowed_hosts_setting_extends_the_origin_check(self):
        with mock.patch.object(proxy, "EXTRA_ALLOWED_HOSTS", {"app.example.com"}):
            resp = await self.client.post("/_stcore/upload_file/x", headers={"Origin": "https://app.example.com"},
                                          cookies={"__session": clerk_token()})
            self.assertEqual(resp.status, 200)

    async def test_session_cookies_are_not_forwarded_to_streamlit(self):
        cookie = "_streamlit_xsrf=abc; __session=SECRET1; theme=dark; amc_session=SECRET2; __client_uat=1; __clerk_db_jwt=SECRET3"
        resp = await self.client.get("/", headers={"Cookie": cookie}, cookies=None)
        # The proxy authenticates via the cookies, so supply a valid one in the header.
        resp = await self.client.get("/", headers={"Cookie": f"{cookie}; __session={clerk_token()}"})
        forwarded = (await resp.json())["cookie"]
        for secret in ("SECRET1", "SECRET2", "SECRET3", "__session", "amc_session", "__client_uat", "__clerk"):
            self.assertNotIn(secret, forwarded)
        self.assertIn("_streamlit_xsrf=abc", forwarded)
        self.assertIn("theme=dark", forwarded)


class JwksCooldownTest(unittest.TestCase):
    def test_unknown_key_ids_cannot_make_us_refetch_the_key_set_repeatedly(self):
        fake = CountingJWKS()
        with mock.patch.object(clerk_auth, "_jwks_client", fake), mock.patch.object(clerk_auth, "_keys_by_kid", {}), \
                mock.patch.object(clerk_auth, "_keys_refreshed_at", None):
            for i in range(50):
                self.assertIsNone(clerk_auth._signing_key(f"random-kid-{i}"))
            self.assertEqual(fake.calls, 1)


class ClerkConfigTest(unittest.TestCase):
    TEST_KEY = "pk_test_dGVzdC1hcHAuY2xlcmsuYWNjb3VudHMuZGV2JA"  # decodes to test-app.clerk.accounts.dev$

    def test_the_nextjs_style_key_name_from_clerk_env_pull_is_accepted(self):
        import subprocess
        import sys
        env = {**os.environ, "CLERK_PUBLISHABLE_KEY": "", "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": self.TEST_KEY, "JWT_SECRET": "s" * 40}
        out = subprocess.run(
            [sys.executable, "-c", "import clerk_auth as c; print(c.ENABLED, c.FRONTEND_HOST)"],
            capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), timeout=60,
        ).stdout.split()
        self.assertEqual(out, ["True", "test-app.clerk.accounts.dev"])

    def test_env_local_key_beats_an_older_key_in_env_but_not_a_real_environment_variable(self):
        local = {"NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": " pk_live_new "}
        environ = {}
        clerk_auth._adopt_local_publishable_key(environ, local)
        self.assertEqual(environ["CLERK_PUBLISHABLE_KEY"], "pk_live_new")  # set before .env is read, so .env cannot override it
        environ = {"CLERK_PUBLISHABLE_KEY": "pk_test_from_azure"}
        clerk_auth._adopt_local_publishable_key(environ, local)
        self.assertEqual(environ["CLERK_PUBLISHABLE_KEY"], "pk_test_from_azure")
        environ = {"NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY": "pk_test_explicit"}
        clerk_auth._adopt_local_publishable_key(environ, local)
        self.assertNotIn("CLERK_PUBLISHABLE_KEY", environ)
        environ = {"CLERK_PUBLISHABLE_KEY": ""}  # explicitly switched off
        clerk_auth._adopt_local_publishable_key(environ, local)
        self.assertEqual(environ["CLERK_PUBLISHABLE_KEY"], "")
        environ = {}
        clerk_auth._adopt_local_publishable_key(environ, {})
        self.assertEqual(environ, {})

    def test_warns_when_the_frontend_host_does_not_resolve(self):
        with mock.patch.object(clerk_auth, "FRONTEND_HOST", "clerk.nonexistent-host.invalid"):
            warnings = clerk_auth.configuration_warnings()
        self.assertTrue(any("does not resolve" in w for w in warnings))

    def test_warns_about_a_production_key_without_authorized_parties(self):
        with mock.patch.object(clerk_auth, "FRONTEND_HOST", "localhost"), \
                mock.patch.object(clerk_auth, "PUBLISHABLE_KEY", "pk_live_x"), mock.patch.object(clerk_auth, "AUTHORIZED_PARTIES", set()):
            self.assertTrue(any("CLERK_AUTHORIZED_PARTIES" in w for w in clerk_auth.configuration_warnings()))
            with mock.patch.object(clerk_auth, "AUTHORIZED_PARTIES", {"https://app.example.com"}):
                self.assertEqual(clerk_auth.configuration_warnings(), [])

    def test_no_warnings_without_clerk(self):
        with mock.patch.object(clerk_auth, "FRONTEND_HOST", ""):
            self.assertEqual(clerk_auth.configuration_warnings(), [])


class PublishableKeyTest(unittest.TestCase):
    def test_frontend_host_is_decoded(self):
        self.assertEqual(
            clerk_auth._frontend_host("pk_test_dGVzdC1hcHAuY2xlcmsuYWNjb3VudHMuZGV2JA"),
            "test-app.clerk.accounts.dev",
        )

    def test_invalid_keys_yield_no_host(self):
        for key in ("", "garbage", "pk_test_", "pk_test_!!!"):
            self.assertEqual(clerk_auth._frontend_host(key), "")


if __name__ == "__main__":
    unittest.main()
