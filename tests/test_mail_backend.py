import sys
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mail_backend as b

MESSAGE = b"From: Customer <customer@example.com>\r\nTo: example@qq.com\r\nSubject: Request\r\nDate: Mon, 05 Oct 2026 03:00:00 +0800\r\nMessage-ID: <test@example.com>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nHello reader"

class FakeIMAP:
    def __init__(self, *args, **kwargs):
        self.calls = []
    def login(self, account, password):
        self.calls.append(("LOGIN", account))
    def logout(self):
        pass
    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\Sent) "/" "Sent Messages"']
    def select(self, mailbox, readonly=False):
        if not readonly:
            raise AssertionError("Mailbox was opened for writes")
        self.calls.append(("EXAMINE", mailbox))
        return "OK", [b"3"]
    def response(self, kind):
        return kind, [b"9"]
    def uid(self, command, *args):
        assert command in {"SEARCH", "FETCH"}
        self.calls.append((command, *args))
        if command == "SEARCH":
            return "OK", [b"1 2 3"]
        if args[1] == "(UID RFC822.SIZE)":
            return "OK", [b"1 (UID 3 RFC822.SIZE 250)"]
        assert "BODY.PEEK[" in args[1]
        return "OK", [(b'1 (UID 3 FLAGS () INTERNALDATE "05-Oct-2026 03:00:00 +0800" RFC822.SIZE 250)', MESSAGE)]

class MailTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeIMAP()
        self.network = patch.object(b.imaplib, "IMAP4_SSL", return_value=self.fake)
        self.key = patch.object(b, "credential", return_value="not-a-real-secret")
        self.account = patch.object(b, "account", return_value="example@qq.com")
        self.network.start(); self.key.start()
        self.account.start()
        self.addCleanup(self.account.stop)
        self.addCleanup(self.network.stop); self.addCleanup(self.key.stop)
    def test_search_readonly_and_pagination(self):
        result = b.search("sent", since="2026-10-05", limit=1)
        self.assertEqual(result["messages"][0]["uid"], 3)
        self.assertEqual(result["next_before_uid"], 3)
        self.assertIn(("EXAMINE", '"Sent Messages"'), self.fake.calls)
        self.assertFalse(result["messages"][0]["seen"])
    def test_peek_body_and_preserve_unread(self):
        result = b.read("inbox", 3, 9)
        self.assertEqual(result["text"], "Hello reader")
        self.assertFalse(result["seen"])
        self.assertTrue(result["content_is_untrusted"])
        self.assertEqual(self.fake.calls[-1][-1], "(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[])")
    def test_stale_uidvalidity_blocks_fetch(self):
        with self.assertRaises(b.MailError):
            b.read("inbox", 3, 8)
        self.assertFalse(any(x[0] == "FETCH" for x in self.fake.calls))
    def test_search_injection_and_bad_scope(self):
        with self.assertRaises(b.MailError):
            b.search(sender="person\r\nDELETE INBOX")
        with self.assertRaises(b.MailError):
            b.search(mailbox="trash")
        self.assertEqual(b.quoted_search('a"b\\c'), b'"a\\"b\\\\c"')
    def test_large_message_never_downloaded(self):
        original = self.fake.uid
        def oversized(command, *args):
            if command == "FETCH" and args[1] == "(UID RFC822.SIZE)":
                self.fake.calls.append((command, *args))
                return "OK", [b"1 (UID 3 RFC822.SIZE 3000000)"]
            return original(command, *args)
        self.fake.uid = oversized
        with self.assertRaises(b.MailError):
            b.read("inbox", 3, 9)
        self.assertFalse(any("BODY.PEEK[]" in str(x) for x in self.fake.calls))
    def test_html_does_not_include_script(self):
        parser = b.TextHTML()
        parser.feed('<p>Hello</p><script>exfiltrate()</script><img src="https://example.com/track">')
        self.assertEqual("".join(parser.parts).strip(), "Hello")

    def test_selected_account_keychain_lookup(self):
        self.key.stop()
        with patch.object(b, "keychain") as store:
            store.return_value.get_password.return_value = "not-a-real-secret"
            self.assertEqual(b.credential(), "not-a-real-secret")
            store.return_value.get_password.assert_called_once_with("qq-mail-mcp", "example@qq.com")

    def test_invalid_account_prevents_login(self):
        with self.assertRaises(b.MailError):
            with b.connect(code="not-a-real-secret", username="example@qq.com\r\nBAD"):
                pass
        self.assertFalse(any(x[0] == "LOGIN" for x in self.fake.calls))


class ConfigTests(unittest.TestCase):
    def test_missing_configuration_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}, clear=True):
                with self.assertRaisesRegex(b.MailError, "Run qq-mail-configure"):
                    b.account()

    def test_environment_override_requires_qq_address(self):
        with patch.dict(os.environ, {"QQ_MAIL_ACCOUNT": "example@invalid.test"}):
            with self.assertRaises(b.MailError):
                b.account()

    def test_selected_config_account(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}, clear=True):
                path = b.config_path()
                path.parent.mkdir()
                path.write_text('{"account":"example@qq.com"}')
                self.assertEqual(b.account(), "example@qq.com")

if __name__ == "__main__":
    unittest.main()
