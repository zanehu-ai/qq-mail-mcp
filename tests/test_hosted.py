import asyncio
import base64
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from urllib.parse import parse_qs, urlsplit
import unittest
from unittest.mock import AsyncMock, Mock, patch

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import httpx
from authlib.integrations.starlette_client import OAuth
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

import mail_backend as backend
from hosted.app import Settings, create_app
from hosted.security import JWTVerifier, SCOPE, Vault

ORIGIN = "https://qq-mail.example.test"
ISSUER = "https://identity.example.test/"
RESOURCE = ORIGIN + "/mcp"
CODE = "abcdefghijklmnop"


class HostedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(ORIGIN, ISSUER, ISSUER + "jwks", "web-client", "s" * 32,
            "c" * 32, Fernet.generate_key().decode(), str(Path(self.tmp.name) / "vault.db"))
        self.vault = Vault(self.settings.database, self.settings.vault_key)

    def test_vault_isolates_users_issuers_and_encrypts_all_mail_credentials(self):
        self.vault.put(ISSUER, "alice", "alice@qq.com", CODE)
        self.vault.put(ISSUER, "bob", "bob@qq.com", "ponmlkjihgfedcba")
        self.assertEqual(self.vault.get(ISSUER, "alice")["username"], "alice@qq.com")
        self.assertEqual(self.vault.get(ISSUER, "bob")["username"], "bob@qq.com")
        with self.assertRaises(backend.MailError):
            self.vault.get("https://another.example.test/", "alice")
        raw = Path(self.settings.database).read_bytes()
        for secret in (CODE.encode(), b"alice@qq.com", b"bob@qq.com", b"alice"):
            self.assertNotIn(secret, raw)
        self.assertEqual(Path(self.settings.database).stat().st_mode & 0o777, 0o600)
        # Moving valid ciphertext into another user's row must not grant access.
        with sqlite3.connect(self.settings.database) as db:
            db.execute("UPDATE mailboxes SET sealed=(SELECT sealed FROM mailboxes WHERE owner=?) WHERE owner=?",
                (self.vault.owner(ISSUER, "alice"), self.vault.owner(ISSUER, "bob")))
        with self.assertRaises(backend.MailError):
            self.vault.get(ISSUER, "bob")
        self.vault.remove(ISSUER, "alice")
        with self.assertRaises(backend.MailError):
            self.vault.get(ISSUER, "alice")

    def test_browser_session_expires_and_logout_invalidates_replayed_cookie(self):
        sid = self.vault.new_session(ISSUER, "alice")
        self.assertEqual(self.vault.session(sid)["subject"], "alice")
        with patch("hosted.security.time.time", return_value=time.time() + 901):
            self.assertIsNone(self.vault.session(sid))
        self.vault.end_session(sid)
        self.assertIsNone(self.vault.session(sid))

    def test_missing_and_wrong_audience_mcp_tokens_rejected_before_mail_access(self):
        verifier = Mock(verify_token=AsyncMock(return_value=None))
        app = create_app(self.settings, vault=self.vault, verifier=verifier)
        with TestClient(app, base_url=ORIGIN) as client, patch.object(backend, "health") as health:
            response = client.post("/mcp", json={})
            self.assertEqual(response.status_code, 401)
            self.assertIn("resource_metadata", response.headers["www-authenticate"])
            response = client.post("/mcp", json={}, headers={"Authorization": "Bearer invalid"})
            self.assertEqual(response.status_code, 401)
            verifier.verify_token.return_value = AccessToken(token="wrong", client_id="c", subject="alice",
                scopes=[SCOPE], resource="https://wrong.example.test/mcp", expires_at=int(time.time()) + 60)
            self.assertEqual(client.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"}).status_code, 401)
            health.assert_not_called()
            metadata = client.get("/.well-known/oauth-protected-resource/mcp").json()
            self.assertEqual(metadata["resource"], RESOURCE)
            self.assertEqual(metadata["authorization_servers"], [ISSUER])

    def test_browser_link_requires_verified_login_origin_csrf_and_successful_imap(self):
        oidc = Mock(authorize_access_token=AsyncMock(return_value={
            "id_token": "verified-by-oidc-client", "userinfo": {"iss": ISSUER, "sub": "alice"}}))
        app = create_app(self.settings, vault=self.vault, verifier=Mock(), oauth=oidc)
        with TestClient(app, base_url=ORIGIN) as client, patch.object(backend, "health", return_value={"connected": True}) as health:
            data = {"address": "alice@qq.com", "code": CODE, "csrf": "invalid"}
            self.assertEqual(client.post("/mailbox/link", data=data, headers={"Origin": ORIGIN}).status_code, 401)
            self.assertEqual(client.get("/callback").status_code, 200)
            html = client.get("/").text
            csrf = re.search('name="csrf" value="([^"]+)"', html)[1]
            data["csrf"] = csrf
            self.assertEqual(client.post("/mailbox/link", data=data, headers={"Origin": "https://evil.example.test"}).status_code, 403)
            self.assertEqual(client.post("/mailbox/link", data={**data, "csrf": "wrong"}, headers={"Origin": ORIGIN}).status_code, 403)
            self.assertEqual(client.post("/mailbox/link", content=b"x" * 5000,
                headers={"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"}).status_code, 413)
            health.assert_not_called()
            health.side_effect = backend.MailError("QQ IMAP connection failed.")
            self.assertEqual(client.post("/mailbox/link", data=data, headers={"Origin": ORIGIN}).status_code, 400)
            with self.assertRaises(backend.MailError):
                self.vault.get(ISSUER, "alice")
            health.side_effect = None
            response = client.post("/mailbox/link", data=data, headers={"Origin": ORIGIN}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            health.assert_called_with(username="alice@qq.com", code=CODE)
            self.assertEqual(self.vault.get(ISSUER, "alice")["username"], "alice@qq.com")
            # Cookie must never contain mailbox address or code, even decoded.
            cookie = client.cookies.get("__Host-qq-mail-session")
            payload = base64.b64decode(cookie.split(".")[0])
            self.assertNotIn(CODE.encode(), payload)
            self.assertNotIn(b"alice@qq.com", payload)
            csrf = re.search('name="csrf" value="([^"]+)"', client.get("/").text)[1]
            self.assertEqual(client.post("/mailbox/unlink", data={"csrf": csrf}, headers={"Origin": ORIGIN}, follow_redirects=False).status_code, 303)
            with self.assertRaises(backend.MailError):
                self.vault.get(ISSUER, "alice")
            csrf = re.search('name="csrf" value="([^"]+)"', client.get("/").text)[1]
            replay = client.cookies.get("__Host-qq-mail-session")
            client.post("/logout", data={"csrf": csrf}, headers={"Origin": ORIGIN})
            client.cookies.set("__Host-qq-mail-session", replay)
            self.assertIn("Sign in to connect", client.get("/").text)

    def test_actual_oidc_client_rejects_callback_without_state(self):
        app = create_app(self.settings, vault=self.vault, verifier=Mock())
        with TestClient(app, base_url=ORIGIN) as client:
            self.assertEqual(client.get("/callback?code=untrusted", follow_redirects=False).status_code, 400)
            self.assertIsNone(client.cookies.get("__Host-qq-mail-session"))

    def test_actual_oidc_pkce_state_nonce_signature_and_replay(self):
        signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing.public_key()))
        jwk.update(kid="provider-key", use="sig", alg="RS256")
        authorization = {}
        def transport(request):
            if request.url.path == "/.well-known/openid-configuration":
                return httpx.Response(200, json={"issuer": ISSUER, "authorization_endpoint": ISSUER + "authorize",
                    "token_endpoint": ISSUER + "token", "jwks_uri": ISSUER + "jwks",
                    "code_challenge_methods_supported": ["S256"], "id_token_signing_alg_values_supported": ["RS256"]})
            if request.url.path == "/jwks":
                return httpx.Response(200, json={"keys": [jwk]})
            if request.url.path == "/token":
                form = parse_qs(request.content.decode())
                verifier = form["code_verifier"][0]
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                self.assertEqual(challenge, authorization["code_challenge"][0])
                now = int(time.time())
                token = jwt.encode({"iss": ISSUER, "aud": "web-client", "sub": "alice", "iat": now,
                    "exp": now + 300, "nonce": authorization["nonce"][0]}, signing,
                    algorithm="RS256", headers={"kid": "provider-key"})
                return httpx.Response(200, json={"access_token": "test-only", "token_type": "Bearer", "id_token": token})
            raise AssertionError("Unexpected identity-provider request")
        registry = OAuth()
        oauth = registry.register("identity", client_id="web-client", client_secret="s" * 32,
            server_metadata_url=ISSUER + ".well-known/openid-configuration",
            client_kwargs={"scope": "openid", "code_challenge_method": "S256", "transport": httpx.MockTransport(transport)})
        app = create_app(self.settings, vault=self.vault, verifier=Mock(), oauth=oauth)
        with TestClient(app, base_url=ORIGIN) as client:
            login = client.get("/login", follow_redirects=False)
            self.assertEqual(login.status_code, 302)
            authorization.update(parse_qs(urlsplit(login.headers["location"]).query))
            self.assertEqual(authorization["code_challenge_method"], ["S256"])
            self.assertEqual(client.get("/callback?code=test&state=wrong", follow_redirects=False).status_code, 400)
            callback = "/callback?code=test&state=" + authorization["state"][0]
            self.assertEqual(client.get(callback, follow_redirects=False).status_code, 303)
            self.assertIn("No mailbox connected", client.get("/").text)
            self.assertEqual(client.get(callback, follow_redirects=False).status_code, 400)

    def test_concurrent_tool_calls_use_only_authenticated_principal_credentials(self):
        self.vault.put(ISSUER, "alice", "alice@qq.com", CODE)
        self.vault.put(ISSUER, "bob", "bob@qq.com", "ponmlkjihgfedcba")
        app = create_app(self.settings, vault=self.vault, verifier=Mock())
        async def invoke(subject):
            token = AccessToken(token="synthetic", client_id="c", subject=subject,
                scopes=[SCOPE], resource=RESOURCE, claims={"iss": ISSUER})
            handle = auth_context_var.set(AuthenticatedUser(token))
            try:
                result = await app.state.mcp.call_tool("qq_mail_status", {})
                return json.loads(result[0].text)
            finally:
                auth_context_var.reset(handle)
        async def calls():
            return await asyncio.gather(invoke("alice"), invoke("bob"), invoke("missing"))
        with patch.object(backend, "health", side_effect=lambda **kwargs: {"account": kwargs["username"]}), patch.object(backend, "account", side_effect=AssertionError("Local fallback forbidden")), patch.object(backend, "credential", side_effect=AssertionError("Local fallback forbidden")):
            results = asyncio.run(calls())
        self.assertEqual(results[0]["account"], "alice@qq.com")
        self.assertEqual(results[1]["account"], "bob@qq.com")
        self.assertFalse(results[2]["ok"])

    def test_http_mcp_protocol_uses_verified_user_and_disconnect_blocks_access(self):
        signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        verifier = JWTVerifier(ISSUER, RESOURCE, ISSUER + "jwks")
        verifier.keys = Mock()
        verifier.keys.get_signing_key_from_jwt.return_value = Mock(key=signing.public_key())
        app = create_app(self.settings, vault=self.vault, verifier=verifier)
        self.vault.put(ISSUER, "alice", "alice@qq.com", CODE)
        self.vault.put(ISSUER, "bob", "bob@qq.com", "ponmlkjihgfedcba")
        def headers(subject):
            now = int(time.time())
            token = jwt.encode({"iss": ISSUER, "sub": subject, "aud": RESOURCE, "iat": now,
                "exp": now + 300, "scope": SCOPE, "azp": "mcp-client"}, signing, algorithm="RS256")
            return {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18"}
        with TestClient(app, base_url=ORIGIN) as client, patch.object(backend, "health", side_effect=lambda **kwargs: {"account": kwargs["username"]}) as health:
            initialized = client.post("/mcp", headers=headers("alice"), json={"jsonrpc": "2.0", "id": 1,
                "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "offline-test", "version": "1"}}})
            self.assertEqual(initialized.status_code, 200)
            self.assertIn("serverInfo", initialized.json()["result"])
            listed = client.post("/mcp", headers=headers("alice"), json={"jsonrpc": "2.0", "id": 2,
                "method": "tools/list", "params": {}}).json()["result"]["tools"]
            self.assertEqual({tool["name"] for tool in listed}, {"qq_mail_status", "qq_mail_search", "qq_mail_read"})
            self.assertTrue(all(tool["_meta"]["securitySchemes"][0]["scopes"] == [SCOPE] for tool in listed))
            request = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "qq_mail_status", "arguments": {}}}
            for subject in ("alice", "bob"):
                result = client.post("/mcp", headers=headers(subject), json=request).json()["result"]
                self.assertEqual(json.loads(result["content"][0]["text"])["account"], subject + "@qq.com")
            self.vault.remove(ISSUER, "alice")
            health.reset_mock()
            result = client.post("/mcp", headers=headers("alice"), json=request).json()["result"]
            self.assertFalse(json.loads(result["content"][0]["text"])["ok"])
            health.assert_not_called()


class JWTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def test_signature_issuer_audience_expiry_scope_identity_and_lifetime(self):
        verifier = JWTVerifier(ISSUER, RESOURCE, ISSUER + "jwks")
        verifier.keys = Mock()
        verifier.keys.get_signing_key_from_jwt.return_value = Mock(key=self.private.public_key())
        now = int(time.time())
        claims = {"iss": ISSUER, "sub": "alice", "aud": RESOURCE, "iat": now, "exp": now + 300,
            "scope": SCOPE, "azp": "mcp-client"}
        def check(value, key=None):
            return asyncio.run(verifier.verify_token(jwt.encode(value, key or self.private, algorithm="RS256")))
        self.assertEqual(check(claims).subject, "alice")
        for change in ({"iss": "https://evil.example.test/"}, {"aud": "other"}, {"exp": now - 1},
            {"scope": "other:read"}, {"sub": ""}, {"iat": now + 30}, {"exp": now + 10000}, {"azp": ""}):
            with self.subTest(change=change):
                self.assertIsNone(check({**claims, **change}))
        self.assertIsNone(check(claims, self.other))
        self.assertIsNone(asyncio.run(verifier.verify_token(jwt.encode(claims, "x" * 32, algorithm="HS256"))))
        verifier.keys.get_signing_key_from_jwt.side_effect = OSError("unavailable")
        self.assertIsNone(check(claims))


if __name__ == "__main__":
    unittest.main()
