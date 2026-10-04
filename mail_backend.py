"""Bounded, read-only access to one QQ mailbox. No SMTP or IMAP writes."""
import email
import imaplib
import json
import os
import re
import ssl
from contextlib import contextmanager
from datetime import date
from email import policy
from html.parser import HTMLParser
from pathlib import Path

HOST = "imap.qq.com"
KEYCHAIN_SERVICE = "qq-mail-mcp"
MAX_MESSAGE_BYTES = 2_000_000


class MailError(Exception):
    pass


def config_path():
    root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return root / "qq-mail-mcp" / "account.json"


def validate_account(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]*@qq\.com", value, re.I):
        raise MailError("Use a QQ Mail address ending in @qq.com.")
    return value


def account():
    override = os.environ.get("QQ_MAIL_ACCOUNT")
    if override:
        return validate_account(override)
    try:
        value = json.loads(config_path().read_text(encoding="utf-8"))["account"]
    except FileNotFoundError:
        raise MailError("QQ account is missing. Run qq-mail-configure locally.") from None
    except (OSError, ValueError, KeyError, TypeError):
        raise MailError("QQ account configuration is invalid. Run qq-mail-configure locally.") from None
    return validate_account(value)


def keychain():
    # Use macOS Keychain explicitly: never fall back to plaintext backends.
    from keyring.backends.macOS import Keyring
    return Keyring()


def credential(username=None):
    username = validate_account(username) if username else account()
    try:
        code = keychain().get_password(KEYCHAIN_SERVICE, username)
    except Exception:
        raise MailError("macOS Keychain is unavailable or access was denied.") from None
    if not code:
        raise MailError("QQ authorization is missing. Run qq-mail-configure locally.")
    return code


@contextmanager
def connect(code=None, username=None):
    client = None
    try:
        username = validate_account(username) if username else account()
        password = code if code is not None else credential(username)
        client = imaplib.IMAP4_SSL(HOST, 993, ssl_context=ssl.create_default_context(), timeout=25)
        client.login(username, password)
        password = None
        yield client
    except MailError:
        raise
    except (imaplib.IMAP4.error, OSError, ssl.SSLError):
        # Server errors can contain private details; never return raw exceptions.
        raise MailError("QQ IMAP connection failed. Check network, IMAP access and authorization code.") from None
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass


def mailbox_name(raw):
    match = re.fullmatch(rb'\(([^)]*)\)\s+(?:NIL|"(?:[^"\\]|\\.)*")\s+(.+)', raw)
    if not match:
        raise MailError("QQ returned an unsupported mailbox listing.")
    flags, name = match.groups()
    if name.startswith(b'"') and name.endswith(b'"'):
        name = re.sub(rb'\\(.)', rb'\1', name[1:-1])
    return flags.lower().split(), name.decode("ascii")


def folders(client):
    typ, listing = client.list()
    if typ != "OK":
        raise MailError("QQ mailbox listing failed.")
    sent = []
    fallback = []
    for raw in listing:
        if not isinstance(raw, bytes):
            continue
        flags, name = mailbox_name(raw)
        if b"\\noselect" in flags:
            continue
        if b"\\sent" in flags:
            sent.append(name)
        elif name.lower() in {"sent", "sent messages", "sent items"}:
            fallback.append(name)
    candidates = sent or fallback
    if len(candidates) != 1:
        raise MailError("Could not uniquely identify QQ's Sent mailbox.")
    return {"inbox": "INBOX", "sent": candidates[0]}


def select(client, mailbox):
    if mailbox not in {"inbox", "sent"}:
        raise MailError("Only inbox and sent are allowed.")
    name = folders(client)[mailbox]
    # EXAMINE avoids setting flags; quoted names support spaces safely.
    quoted = '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    typ, count = client.select(quoted, readonly=True)
    if typ != "OK":
        raise MailError("Could not open QQ mailbox read-only.")
    _, validity = client.response("UIDVALIDITY")
    if not validity or not validity[0]:
        raise MailError("QQ did not provide UIDVALIDITY.")
    return int(validity[0]), int(count[0])


def quoted_search(value):
    if len(value) > 300 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise MailError("Search terms must be at most 300 characters with no control characters.")
    return ('"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"').encode("utf-8")


def criteria(since=None, sender=None, recipient=None, subject=None, text=None):
    result = []
    if since:
        try:
            day = date.fromisoformat(since)
        except ValueError:
            raise MailError("since must be a date in YYYY-MM-DD format.") from None
        months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
        result += ["SINCE", f"{day.day:02d}-{months[day.month-1]}-{day.year}"]
    for field, value in [("FROM", sender), ("TO", recipient), ("SUBJECT", subject), ("TEXT", text)]:
        if value:
            result += [field, quoted_search(value)]
    return result or ["ALL"]


def header_result(uid, payload, metadata):
    msg = email.message_from_bytes(payload, policy=policy.default)
    received = re.search(rb'INTERNALDATE "([^\"]+)"', metadata)
    size = re.search(rb'RFC822\.SIZE (\d+)', metadata)
    flags = re.search(rb'FLAGS \(([^)]*)\)', metadata)
    return {
        "uid": uid,
        "from": str(msg.get("From", "")), "to": str(msg.get("To", "")),
        "subject": str(msg.get("Subject", "")), "date": str(msg.get("Date", "")),
        "message_id": str(msg.get("Message-ID", "")),
        "received_at": received[1].decode("ascii") if received else None,
        "bytes": int(size[1]) if size else None,
        "seen": b"\\Seen" in flags[1].split() if flags else None,
    }


def search(mailbox="inbox", since=None, sender=None, recipient=None, subject=None, text=None, limit=20, before_uid=None, *, username=None, code=None):
    if not 1 <= limit <= 100 or (before_uid is not None and before_uid < 1):
        raise MailError("limit must be 1..100 and before_uid must be positive.")
    query = criteria(since, sender, recipient, subject, text)
    nonascii = any(isinstance(x, bytes) and not x.isascii() for x in query)
    with connect(code=code, username=username) as client:
        validity, total = select(client, mailbox)
        args = ["CHARSET", "UTF-8", *query] if nonascii else query
        typ, result = client.uid("SEARCH", *args)
        if typ != "OK":
            raise MailError("QQ search failed. The server may not support this search encoding.")
        all_uids = sorted((int(x) for x in result[0].split()), reverse=True)
        eligible = [x for x in all_uids if before_uid is None or x < before_uid]
        page = eligible[:limit]
        messages = []
        if page:
            typ, fetched = client.uid("FETCH", ",".join(map(str, page)),
                "(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])")
            if typ != "OK":
                raise MailError("QQ header retrieval failed.")
            for item in fetched:
                if isinstance(item, tuple):
                    uid = re.search(rb'UID (\d+)', item[0])
                    if uid:
                        messages.append(header_result(int(uid[1]), item[1], item[0]))
        messages.sort(key=lambda x: x["uid"], reverse=True)
        return {"mailbox": mailbox, "uidvalidity": validity, "mailbox_messages": total,
                "matching_messages": len(all_uids), "messages": messages,
                "next_before_uid": page[-1] if len(eligible) > limit else None}


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li"} and not self.hidden:
            self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def read(mailbox, uid, uidvalidity, max_characters=12000, *, username=None, code=None):
    if uid < 1 or uidvalidity < 1 or not 100 <= max_characters <= 30000:
        raise MailError("Use a positive UID and UIDVALIDITY and 100..30000 characters.")
    with connect(code=code, username=username) as client:
        actual, _ = select(client, mailbox)
        if actual != uidvalidity:
            raise MailError("Mailbox identity changed. Search again before reading this UID.")
        typ, info = client.uid("FETCH", str(uid), "(UID RFC822.SIZE)")
        sizes = [re.search(rb'RFC822\.SIZE (\d+)', x) for x in info if isinstance(x, bytes)]
        sizes = [x for x in sizes if x]
        if typ != "OK" or not sizes:
            raise MailError("Message not found.")
        if int(sizes[0][1]) > MAX_MESSAGE_BYTES:
            raise MailError("Message exceeds the 2 MB read limit. Read its headers with search instead.")
        typ, result = client.uid("FETCH", str(uid), "(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[])")
        literals = [x for x in result if isinstance(x, tuple)]
        if typ != "OK" or not literals:
            raise MailError("Message not found.")
        metadata, payload = literals[0]
        msg = email.message_from_bytes(payload, policy=policy.default)
        summary = header_result(uid, payload, metadata)
        body = msg.get_body(preferencelist=("plain", "html"))
        content = ""
        if body:
            try:
                content = body.get_content()
            except (LookupError, UnicodeError):
                content = (body.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
            if body.get_content_type() == "text/html":
                parser = TextHTML()
                parser.feed(content)
                content = "".join(parser.parts)
        summary.update({"mailbox": mailbox, "uidvalidity": actual,
            "text": content[:max_characters], "truncated": len(content) > max_characters,
            "attachments": [{"filename": p.get_filename(), "content_type": p.get_content_type()}
                            for p in msg.iter_attachments()],
            "content_is_untrusted": True})
        return summary


def health(*, username=None, code=None):
    with connect(code=code, username=username) as client:
        result = {"account": validate_account(username) if username else account(), "connected": True, "read_only": True, "mailboxes": {}}
        for mailbox in ("inbox", "sent"):
            validity, count = select(client, mailbox)
            result["mailboxes"][mailbox] = {"uidvalidity": validity, "messages": count}
        return result
