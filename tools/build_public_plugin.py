"""Build a public plugin ZIP from explicit, real HTTPS publication inputs."""
import argparse
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]


def https_url(value):
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        raise argparse.ArgumentTypeError("Use a valid public HTTPS URL.") from None
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or port not in (None, 443):
        raise argparse.ArgumentTypeError("Use a public HTTPS URL without credentials or a custom port.")
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or host == "localhost" or host.endswith((".localhost", ".local", ".example", ".invalid", ".test")) or host in {"example.com", "example.org", "example.net"} or host.endswith((".example.com", ".example.org", ".example.net")):
        raise argparse.ArgumentTypeError("Placeholder, local and control-character URLs are not publication inputs.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise argparse.ArgumentTypeError("Private network URLs are not publication inputs.")
    if parsed.fragment:
        raise argparse.ArgumentTypeError("Use a URL without a fragment.")
    if len(value) > 1024:
        raise argparse.ArgumentTypeError("Publication URLs must be at most 1024 characters.")
    return value


def build(args):
    manifest = json.loads((ROOT / "publication/listing.json").read_text())
    extension = manifest["extensions"]["com.openai"]
    interface = extension["interface"]
    interface.update(websiteURL=args.website_url, supportURL=args.support_url,
        privacyPolicyURL=args.privacy_url, termsOfServiceURL=args.terms_url)
    extension["review"]["demo_recording_url"] = args.demo_url
    cases = extension["review"]["test_cases"]
    if len(cases["positive"]) != 5 or len(cases["negative"]) != 3:
        raise ValueError("Initial review requires five positive and three negative cases.")
    if len(interface["displayName"]) > 30 or len(interface["shortDescription"]) > 30:
        raise ValueError("Listing name and subtitle must be at most 30 characters.")
    mcp = {"$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        "mcpServers": {"qq-mail": {"type": "streamable-http", "url": args.mcp_url}}}
    output = Path(args.output)
    if output.exists():
        raise FileExistsError("Choose a new output path; existing archives are not overwritten.")
    icon = (ROOT / "publication/assets/icon.png").read_bytes()
    skill = (ROOT / "skills/qq-mail/SKILL.md").read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "x", compression=ZIP_DEFLATED) as archive:
        archive.writestr("plugin.json", json.dumps(manifest, indent=2) + "\n")
        archive.writestr("mcp.json", json.dumps(mcp, indent=2) + "\n")
        archive.writestr("skills/qq-mail/SKILL.md", skill)
        archive.writestr("assets/icon.png", icon)
    print(f"Created {output}. Hosted access and review-case verification are separate required checks.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("mcp", "website", "support", "privacy", "terms", "demo"):
        parser.add_argument(f"--{name}-url", required=True, type=https_url)
    parser.add_argument("--output", default="dist/qq-mail-public.zip")
    args = parser.parse_args()
    try:
        build(args)
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
