# QQ Mail MCP (Unofficial)

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-111111?style=flat)
![MCP Read-Only](https://img.shields.io/badge/MCP-read--only-111111?style=flat)
![License: MIT](https://img.shields.io/badge/license-MIT-111111?style=flat)

<details>
<summary>简体中文简介（点击展开）</summary>

面向 macOS 的**最小权限只读 QQ 邮箱 MCP 连接器**（Python 3.12+ / 官方 MCP SDK / MIT 协议）。仅暴露 `qq_mail_status`、`qq_mail_search`、`qq_mail_read` 三个只读工具（基于 IMAP `EXAMINE` / `BODY.PEEK`，不改未读状态，零发信/删信/移动权限）；16 位授权码零明文托管于 **macOS Keychain**，内置 TLS 校验、单封阅读上限及非信任邮件防拉取护栏。

- **已验证项**：自动化 `unittest` 套件与 `tests/check_mcp.py` 均已通过，验证了 MCP 初始化握手、只读工具注解及缺凭证快速失败（Mock 隔离环境）。
- **本地实机配置**：首次连接真实邮箱时，通过 `qq-mail-configure` 交互输入邮箱与 16 位 IMAP 授权码后立即写入 macOS 钥匙串（不在磁盘保存明文密码）。

</details>

A local, read-only QQ Mail MCP connector for macOS. This project is independent of Tencent and OpenAI. It uses QQ's IMAP service and the official MCP Python SDK.

## Security Design Highlights

- **Least-Privilege Read-Only Access**: Exposes strictly 3 read-only tools (`qq_mail_status`, `qq_mail_search`, `qq_mail_read`) scoped to Inbox and Sent via IMAP `EXAMINE` / `BODY.PEEK`—preserving unread flags with zero SMTP, send, delete, move, or settings permissions.
- **Zero-Plaintext Credentials**: Stores the 16-letter QQ IMAP authorization code exclusively in **macOS Keychain** (`qq-mail-mcp` service), never in workspace files, issues, or plaintext config files.
- **Bounded & Untrusted-Input Guardrails**: Enforces TLS certificate verification, `UIDVALIDITY` checks, 2 MB / 30,000-character read caps, and treats email bodies strictly as untrusted data without fetching embedded URLs, images, or scripts.

## Status & Verification

- **Automated Verification Passed (Mock & Contract Tests)**: `python -m unittest discover -s tests -v` and `tests/check_mcp.py` verify MCP protocol initialization, read-only tool annotations (`readOnlyHint`), byte/character caps, `UIDVALIDITY` checks, and fail-closed missing-credential errors using isolated mock fixtures (zero hardcoded credentials).
- **Local Real-Device Configuration**: Experimental connector. Live QQ Mail IMAP authentication runs locally on your Mac only after you execute `qq-mail-configure` to store the 16-letter QQ IMAP authorization code directly in macOS Keychain. GitHub publication distributes source under MIT License; it does not establish approval or listing in any third-party public plugin directory.

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
