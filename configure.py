"""Verify QQ authorization interactively, then save it in macOS Keychain."""
import argparse
import getpass
import json
import os
import re
import sys
import tempfile
from pathlib import Path
import mail_backend as backend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", help="QQ Mail address; not an authorization code")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        sys.exit("Run qq-mail-configure in a local terminal. Do not put credentials in chat or command arguments.")
    try:
        username = backend.validate_account(args.account or input("QQ Mail address: ").strip())
        override = os.environ.get("QQ_MAIL_ACCOUNT")
        if override and backend.validate_account(override) != username:
            sys.exit("QQ_MAIL_ACCOUNT selects another account. Unset it before configuring this account.")
        print("Enter the QQ 16-letter authorization code. Input is hidden.")
        code = getpass.getpass("QQ authorization code: ").strip()
        if not re.fullmatch(r"[A-Za-z]{16}", code):
            sys.exit("Expected the 16-letter QQ authorization code.")
        counts = {}
        with backend.connect(code, username=username) as client:
            for mailbox in ("inbox", "sent"):
                validity, count = backend.select(client, mailbox)
                counts[mailbox] = {"uidvalidity": validity, "messages": count}
        backend.keychain().set_password(backend.KEYCHAIN_SERVICE, username, code)
        code = None
        path = backend.config_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Only the selected address goes in this file; the secret stays in Keychain.
        fd, name = tempfile.mkstemp(prefix=".account-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"account": username}, stream)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        print(json.dumps({"connected": True, "read_only": True, "mailboxes": counts}, indent=2))
        print("Saved in macOS Keychain. Reload MCP connections in your client.")
    except backend.MailError as error:
        sys.exit(str(error))
    except (EOFError, KeyboardInterrupt):
        sys.exit("Setup canceled.")
    except Exception:
        sys.exit("Local setup failed. No authorization code was written to a file.")


if __name__ == "__main__":
    main()
