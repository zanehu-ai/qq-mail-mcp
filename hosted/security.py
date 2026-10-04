"""Configured OAuth verification and encrypted, principal-bound persistence."""
import asyncio
import base64
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
import jwt
from mcp.server.auth.provider import AccessToken

import mail_backend

SCOPE = "qq-mail:read"


def https(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or parsed.query
            or parsed.port not in (None, 443)
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)):
        raise ValueError("Hosted URLs must use HTTPS without credentials, query or fragment.")
    return value


def principal(issuer, subject):
    if not isinstance(subject, str) or not 1 <= len(subject) <= 255 or any(ord(c) < 32 or ord(c) == 127 for c in subject):
        raise ValueError("Invalid user identity.")
    return json.dumps([issuer, subject], separators=(",", ":"))


class JWTVerifier:
    """Never select issuer, audience, JWKS endpoint or algorithm from a token."""
    def __init__(self, issuer, resource, jwks_url, max_lifetime=600):
        self.issuer = https(issuer)
        self.resource = https(resource)
        self.keys = jwt.PyJWKClient(https(jwks_url), timeout=5, lifespan=60)
        self.max_lifetime = max_lifetime

    def _verify(self, token):
        try:
            if len(token) > 16384:
                return None
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                return None
            key = self.keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=self.issuer,
                audience=self.resource, options={"require": ["iss", "sub", "aud", "exp", "iat"]})
            principal(self.issuer, claims["sub"])
            issued, expiry = claims["iat"], claims["exp"]
            if type(issued) is not int or type(expiry) is not int or not 0 < expiry - issued <= self.max_lifetime:
                return None
            scopes = claims.get("scope", "")
            if not isinstance(scopes, str) or SCOPE not in scopes.split():
                return None
            client_id = claims.get("client_id") or claims.get("azp")
            if not isinstance(client_id, str) or not client_id:
                return None
            return AccessToken(token=token, client_id=client_id, subject=claims["sub"],
                scopes=scopes.split(), expires_at=expiry, resource=self.resource,
                claims={"iss": self.issuer})
        except Exception:
            # Provider/network/signature errors fail closed without logging private tokens.
            return None

    async def verify_token(self, token):
        return await asyncio.to_thread(self._verify, token)


class Vault:
    """One encrypted credential record per (issuer, sub), never per email alias."""
    def __init__(self, path, encryption_key):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cipher = Fernet(encryption_key.encode())
        self.index_key = base64.urlsafe_b64decode(encryption_key)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        with closing(self._db()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS mailboxes (owner TEXT PRIMARY KEY, sealed BLOB NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, sealed BLOB NOT NULL, expiry INTEGER NOT NULL)")

    def _db(self):
        return sqlite3.connect(self.path, timeout=5)

    def owner(self, issuer, subject):
        identity = principal(issuer, subject)
        return hmac.new(self.index_key, identity.encode(), hashlib.sha256).hexdigest()

    def _seal(self, value):
        return self.cipher.encrypt(json.dumps(value, separators=(",", ":")).encode())

    def _open(self, value):
        try:
            return json.loads(self.cipher.decrypt(value))
        except (InvalidToken, ValueError, TypeError):
            raise mail_backend.MailError("Stored mailbox authorization is unavailable.") from None

    def put(self, issuer, subject, username, code):
        username = mail_backend.validate_account(username)
        if not isinstance(code, str) or not re.fullmatch("[A-Za-z]{16}", code):
            raise mail_backend.MailError("Use the 16-letter QQ IMAP authorization code.")
        owner = self.owner(issuer, subject)
        sealed = self._seal({"owner": owner, "username": username, "code": code})
        with closing(self._db()) as db, db:
            db.execute("INSERT INTO mailboxes VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET sealed=excluded.sealed", (owner, sealed))

    def get(self, issuer, subject):
        owner = self.owner(issuer, subject)
        with closing(self._db()) as db:
            row = db.execute("SELECT sealed FROM mailboxes WHERE owner=?", (owner,)).fetchone()
        if not row:
            raise mail_backend.MailError("Connect your own QQ mailbox on the service website first.")
        record = self._open(row[0])
        if record.get("owner") != owner:
            raise mail_backend.MailError("Stored mailbox authorization is unavailable.")
        return {"username": record["username"], "code": record["code"]}

    def remove(self, issuer, subject):
        with closing(self._db()) as db, db:
            db.execute("DELETE FROM mailboxes WHERE owner=?", (self.owner(issuer, subject),))

    def new_session(self, issuer, subject):
        principal(issuer, subject)
        sid = secrets.token_urlsafe(32)
        identity = self._seal({"session": sid, "issuer": issuer, "subject": subject})
        with closing(self._db()) as db, db:
            db.execute("DELETE FROM sessions WHERE expiry<=?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (hashlib.sha256(sid.encode()).hexdigest(), identity, int(time.time()) + 900))
        return sid

    def session(self, sid):
        if not isinstance(sid, str) or len(sid) > 100:
            return None
        with closing(self._db()) as db:
            row = db.execute("SELECT sealed FROM sessions WHERE id=? AND expiry>?", (hashlib.sha256(sid.encode()).hexdigest(), int(time.time()))).fetchone()
        if not row:
            return None
        value = self._open(row[0])
        return value if value.get("session") == sid else None

    def end_session(self, sid):
        if isinstance(sid, str):
            with closing(self._db()) as db, db:
                db.execute("DELETE FROM sessions WHERE id=?", (hashlib.sha256(sid.encode()).hexdigest(),))
