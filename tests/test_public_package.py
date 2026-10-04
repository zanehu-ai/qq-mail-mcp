import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_builder", ROOT / "tools/build_public_plugin.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PublicPackageTests(unittest.TestCase):
    def test_local_placeholder_or_credential_urls_rejected(self):
        for value in ("http://service.fixture.dev/mcp", "https://localhost/mcp",
                      "https://10.0.0.1/mcp", "https://example.com/mcp",
                      "https://user:secret@service.fixture.dev/mcp", "https://service.fixture.dev/mcp\n"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    builder.https_url(value)

    def test_archive_excludes_source_and_private_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            (fixture / "publication/assets").mkdir(parents=True)
            (fixture / "skills/qq-mail").mkdir(parents=True)
            for name in ("publication/listing.json", "publication/assets/icon.png", "skills/qq-mail/SKILL.md"):
                (fixture / name).write_bytes((ROOT / name).read_bytes())
            (fixture / ".env").write_text("PRIVATE_FIXTURE=not-a-real-secret")
            (fixture / "account.json").write_text('{"account":"private-fixture@qq.com"}')
            (fixture / "server.py").write_text("PRIVATE_FIXTURE = 'source-not-for-plugin-zip'")
            args = argparse.Namespace(output=str(fixture / "test-only.zip"),
                mcp_url="https://service.fixture.dev/mcp", website_url="https://service.fixture.dev/",
                support_url="https://service.fixture.dev/support", privacy_url="https://service.fixture.dev/privacy",
                terms_url="https://service.fixture.dev/terms", demo_url="https://service.fixture.dev/demo")
            with patch.object(builder, "ROOT", fixture):
                builder.build(args)
                with self.assertRaises(FileExistsError):
                    builder.build(args)
            with ZipFile(args.output) as archive:
                self.assertEqual(set(archive.namelist()), {"plugin.json", "mcp.json", "skills/qq-mail/SKILL.md", "assets/icon.png"})
                metadata = json.loads(archive.read("plugin.json"))
                cases = metadata["extensions"]["com.openai"]["review"]["test_cases"]
                self.assertEqual((len(cases["positive"]), len(cases["negative"])), (5, 3))
                text = b"".join(archive.read(name) for name in archive.namelist())
                self.assertNotIn(b"PRIVATE_FIXTURE", text)
                self.assertNotIn(b"private-fixture@qq.com", text)
                self.assertEqual(json.loads(archive.read("mcp.json"))["mcpServers"]["qq-mail"]["type"], "streamable-http")


if __name__ == "__main__":
    unittest.main()
