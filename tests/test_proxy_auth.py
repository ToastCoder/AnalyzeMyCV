# AnalyzeMyCV
# tests/test_proxy_auth.py
"""Clerk session handling in proxy.py, with a fake upstream and a locally generated Clerk key."""

import gzip
import time
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest import mock

import jwt
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestServer
from cryptography.hazmat.primitives.asymmetric import rsa

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


class FakeJWKS:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=CLERK_KEY.public_key())


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
            mock.patch.object(clerk_auth, "_jwks_client", FakeJWKS()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addAsyncCleanup(self.upstream.close)
        # A fresh app per test: aiohttp applications can't be reused across event loops.
        app = web.Application(client_max_size=proxy.MAX_REQUEST_BYTES, middlewares=[proxy.auth_middleware])
        app.cleanup_ctx.append(proxy.create_client_session)
        app.router.add_get(proxy.SIGN_IN_PATH, proxy.sign_in_page)
        app.router.add_get(proxy.SIGN_OUT_PATH, proxy.sign_out_page)
        app.router.add_route("*", "/{path_info:.*}", proxy.handle_catchall)
        return app

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


class PublishableKeyTest(unittest.TestCase):
    def test_frontend_host_is_decoded(self):
        self.assertEqual(
            clerk_auth._frontend_host("pk_test_ZnVuLWZveGhvdW5kLTg5NjguY2xlcmsuYWNjb3VudHMuZGV2JA"),
            "fun-foxhound-8968.clerk.accounts.dev",
        )

    def test_invalid_keys_yield_no_host(self):
        for key in ("", "garbage", "pk_test_", "pk_test_!!!"):
            self.assertEqual(clerk_auth._frontend_host(key), "")


if __name__ == "__main__":
    unittest.main()
