# Public directory submission preparation

Status: **draft, not submitted, not hosted**. `listing.json` contains draft listing text and the five positive / three negative cases required for initial MCP review. These cases have not been run against a dedicated hosted review account. They are review plans, not test results.

The existing root plugin remains the local macOS connector. Do not upload that local stdio package as a working remote mail service. The public package needs a hosted HTTPS Streamable HTTP endpoint and per-user authorization.

## Current gates

1. Developer identity verification. The signed-in OpenAI Platform portal currently requires verification before accepting an upload. The publisher completes this in the portal.
2. Select the public service's domain and hosting account.
3. Implement remote user authentication, mailbox linking and isolation. Users authorize their own QQ mailboxes. Never use a shared service-level mailbox or the developer's personal mailbox as a fallback.
4. Deploy the HTTPS MCP endpoint with authentication discovery. Store mailbox authorization codes encrypted in the hosted service's secret/storage system; never put them in GitHub, a plugin ZIP, tool arguments or logs. Do not expose the existing local Keychain server anonymously.
5. Publish the actual product website, support page, privacy policy and service terms. Policy wording must describe the deployed service's real collection, retention, deletion and recipients; the local connector's behavior is not a hosted service policy.
6. Complete the portal's domain verification challenge without replacing another product's challenge.
7. Create a dedicated review account with sample data; keep credentials in the portal's private reviewer form. Run all five positive and three negative cases, including cross-user isolation and unchanged Seen flags.
8. Record the working hosted flow and provide the reviewer-accessible video URL.
9. Build the public ZIP, upload, resolve scans and complete review attestations. After OpenAI approval, publish the approved version.

## Build the ZIP after deployment

`tools/build_public_plugin.py` takes the real HTTPS endpoint, website/support/privacy/terms URLs, and demo recording URL. It refuses placeholder/local URLs and packages only an explicit manifest, one remote MCP configuration, one skill and the generated generic envelope icon. It does not copy Python source, configuration, credentials, `.venv`, screenshots or Git history into the ZIP.

```sh
python3 tools/build_public_plugin.py --help
```

The URL inputs are required intentionally. A successful local archive build does not prove endpoint reachability, domain verification, OAuth interoperability, publisher verification, legal review, actual review-case success, OpenAI approval or public discoverability.

## Hosting requirements

The runtime must support outbound certificate-verified TCP/TLS to `imap.qq.com:993`, HTTPS serving for Streamable HTTP, persistent encrypted credential storage, a managed or well-tested OAuth provider, per-user authorization and operational controls. Platform selection depends on the hosting account and domain the publisher chooses.

OpenAI API inference is not required by this connector. The previously discussed API key was for a private Secure MCP Tunnel; it is separate from the public HTTPS submission path.

## Official references

- [Submission and publishing](https://developers.openai.com/plugins/deploy/submission)
- [Remote MCP authentication](https://developers.openai.com/plugins/build/auth)
- [Production endpoint requirements](https://developers.openai.com/plugins/build/mcp-server)
