# Hosted QQ Mail service

Implementation draft. No hosted identity provider has been configured, no real
mailbox has been linked to this service, and no public endpoint is deployed.

`qq-mail-web` serves authenticated Streamable HTTP MCP at `/mcp` and browser
mailbox connection settings at `/`. It uses an external production OIDC/OAuth
provider, Authlib for browser authorization code + PKCE, the official MCP SDK
for discovery and authorization middleware, and PyJWT for RS256 access tokens.
The existing macOS stdio connector remains a separate entry point.

## Identity provider contract

Select a production provider that supports MCP OAuth 2.1 with S256, resource
indicators, and predefined clients or CIMD/DCR. The existing OpcOrbit
`apps/auth` README labels that service a staging spike; this draft does not
promote it to production.

- Configure this resource: `https://qq-mail.opcorbit.com/mcp`.
- Configure scope `qq-mail:read`; issue **user** access tokens, not service grants.
- Access tokens must use RS256 and contain the exact configured `iss`, this
  `aud`, a stable user `sub`, integer `iat`/`exp`, the scope in a space-separated
  `scope` string, and `client_id` or `azp`. Maximum token lifetime is 600 seconds.
- Do not enable client-credentials grants for this user-mailbox resource. Do
  not assign service identities the same subject namespace as human users.
- Configure a separate confidential browser OIDC client with `openid`, PKCE,
  and exact callback `https://qq-mail.opcorbit.com/callback`. Its ID token and
  MCP access token must identify the same user with the same issuer and subject.
- The provider publishes OIDC discovery and serves a trusted HTTPS JWKS URL.
  Identity-provider logout/revocation takes effect at MCP token expiration
  (at most ten minutes); provider introspection is not implemented here.
- Configure actual ChatGPT/Codex client callbacks using the values displayed
  by their connection setup, rather than guessing callback URLs.

The service does not issue OAuth tokens or implement an authorization server.
A Google sign-in alone does not provide MCP resource-scoped access tokens.

## Runtime configuration

Install the hosted extra in a dedicated Python 3.12 environment:

```sh
python -m pip install '.[hosted]'
```

Required environment values:

| Variable | Value |
| --- | --- |
| `QQ_PUBLIC_ORIGIN` | `https://qq-mail.opcorbit.com` |
| `QQ_OIDC_ISSUER` | Provider's exact HTTPS issuer, including its trailing slash if advertised |
| `QQ_OIDC_JWKS_URL` | Trusted provider JWKS URL |
| `QQ_OIDC_CLIENT_ID` | Browser client ID |
| `QQ_OIDC_CLIENT_SECRET_FILE` | Private file containing that client's secret |
| `QQ_SESSION_SECRET_FILE` | Private file containing a random secret of at least 32 characters |
| `QQ_VAULT_KEY_FILE` | Private file containing a persistent Fernet key |
| `QQ_VAULT_DATABASE` | Private persistent SQLite path; default `/data/qq-mail.sqlite3` |

Secret files must have mode 0600 and be readable only by the service account.
Use `Fernet.generate_key()` for the vault key and a cryptographically random
session secret. Provision them in the host secret system, never in Git,
command arguments, tool calls, screenshots, or public plugin packages.

Run `qq-mail-web`. It binds only `127.0.0.1:18321`; configure an HTTPS ingress
for the selected domain. Trust forwarded headers only from local ingress.
Apply a small body limit and request/concurrency limits there; keep access
logging off on OAuth callbacks and connection forms, and do not log request
bodies, Authorization headers, cookies, mail content, or credentials.

Allow outbound certificate-verified TLS to the issuer and to `imap.qq.com:993`.
Preserve a private persistent data directory and the encryption key across
releases. Back up the encrypted database and key separately with access
controls and a defined retention/deletion policy. Losing the key makes
existing mailbox connections unreadable. Restore must not resurrect an
intentionally disconnected mailbox without the user's consent.

## User and data boundaries

The user signs in, enables QQ IMAP, and enters their address and 16-letter QQ
authorization code on the connection page. The service verifies Inbox and
Sent using read-only IMAP before storing it. QQ's code permits access beyond
these tools; users should revoke the code in QQ Mail if it is compromised.

Mailbox address and code are encrypted together. The record is indexed by an
HMAC of `(issuer, sub)` and the ciphertext is bound to that identity. Mail
tools have no account/credential arguments and never fall back to the Mac's
Keychain, account configuration, or a shared service mailbox. Server-side
browser sessions expire after 15 minutes; logout invalidates the session.
Cookie content contains no mailbox address, authorization code, or OAuth token.

Connection forms require the configured Origin plus a session CSRF token.
Disconnection removes the active credential row, so later tool calls cannot
retrieve it. It does not revoke the authorization code at QQ or guarantee
physical erasure from SQLite free pages or historical backups. Explain the
actual backup retention in the published privacy policy.

Message bodies are returned only on request and are not saved by this service.
Reading preserves Seen flags; attachment metadata only. Email remains
untrusted material, and a Sent copy is not proof of delivery.

## Verification before deployment

Offline tests cover JWT signature/issuer/audience/expiry/scope, PKCE/state/nonce
with a synthetic OIDC provider, callback replay, session expiration/logout,
CSRF, encrypted persistence, swapped-record rejection, concurrent user
isolation, and disconnected/missing accounts. They do not establish live
provider interoperability, QQ credentials, production capacity, internet
reachability, real-client acceptance, or directory approval.

Before release: inspect the selected host, configure the real provider,
verify all flows in staging with two separate sample accounts, exercise actual
ChatGPT and Codex OAuth, preserve unread flags, test revoke/disconnect, rehearse
backup recovery without resurrecting revoked records, then deploy and run
the publication review cases. Provide product support/privacy/terms pages
that describe the actual hosted service and operator.
