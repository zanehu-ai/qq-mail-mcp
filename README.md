# QQ Mail MCP (Unofficial)

A local, read-only QQ Mail MCP connector for macOS. This project is independent of Tencent and OpenAI. It uses QQ's IMAP service and the official MCP Python SDK.

## Status

Experimental. MCP initialization, tool discovery and mocked read-only tests pass. Live QQ mailbox authentication has not yet been verified in this project's initial setup. GitHub publication distributes source; it does not establish approval or listing in the OpenAI public plugin directory.

## Install on macOS

Requires macOS Keychain, Python 3.12 or newer, and `uv` available on PATH.

```sh
git clone https://github.com/zanehu-ai/qq-mail-mcp.git
cd qq-mail-mcp
uv tool install .
qq-mail-configure
codex mcp add qq-mail -- qq-mail-mcp
```

Run configuration in your terminal. Enter your QQ address and the 16-letter QQ authorization code at the hidden prompt. Generate the code using QQ Mail's account/security settings after enabling IMAP. Do not paste the code into chat, source, issues, command arguments or environment files.

Setup verifies Inbox and Sent access before saving the code in macOS Keychain under service `qq-mail-mcp`, keyed by your address. Only the selected address is saved in `~/.config/qq-mail-mcp/account.json` (or under `XDG_CONFIG_HOME`). The non-secret `QQ_MAIL_ACCOUNT` environment variable can select another previously authorized account.

The host application must find `qq-mail-mcp` on PATH. You can register its absolute executable path, reported by `command -v qq-mail-mcp`. Start a new session or reload MCP connections afterward.

## Optional local plugin

Install the runtime and authorize it first. Installing the plugin does not install Python dependencies or enter QQ credentials.

```sh
codex plugin marketplace add ./
codex plugin add qq-mail-mcp@qq-mail-community
```

Use either standalone MCP registration or the plugin connection to avoid duplicate tools. Local plugin availability varies by client. This repository includes a portable manifest, MCP configuration, skill and marketplace catalog.

## ChatGPT

Public directory submission preparation is tracked in [publication/README.md](publication/README.md). This repository is not currently a hosted public mail service or an approved directory listing.

ChatGPT web cannot directly start a local stdio process. Connect privately through OpenAI Secure MCP Tunnel where supported, or deploy an authenticated remote MCP transport. A private tunnel needs a configured tunnel, an OpenAI runtime API credential and a running tunnel client on the Mac. Those credentials and configuration are not included here. Account/workspace access may vary.

See [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt) and [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels). Public directory submission requires a separate hosted endpoint and review.

## Tools

| Tool | Purpose |
| --- | --- |
| `qq_mail_status` | Verify live access and return mailbox counts |
| `qq_mail_search` | Search bounded headers in Inbox or Sent |
| `qq_mail_read` | Read bounded text with attachment metadata |

Only Inbox and Sent are accessible. IMAP EXAMINE and BODY.PEEK preserve read/unread flags. No SMTP, deletion, moving messages, rules, settings or attachment downloading. Certificate-verified TLS is required. Reads are capped at 2 MB and 30,000 text characters; UIDVALIDITY rejects stale message identities.

Email is untrusted source material. Embedded URLs, images and scripts are never fetched or executed. A saved Sent copy does not prove recipient delivery. The Mac and MCP client/tunnel must remain available for remote access or monitoring.

## Development checks

```sh
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.lock
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tests/check_mcp.py
```

Tests use fake messages and no credentials. The MCP check verifies initialization, annotations and missing-configuration errors; it does not claim live mailbox access.

## Remove

Remove your client connection, uninstall with `uv tool uninstall qq-mail-mcp`, and remove the named Keychain item using Keychain Access when no longer needed. Revoke the QQ authorization code when it was created exclusively for this connector.
