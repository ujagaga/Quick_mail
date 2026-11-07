#!/usr/bin/env python3
"""Tray icon that polls Gmail for unread inbox mail and shows desktop notifications."""
import os
import signal
import subprocess
import sys
import threading
import webbrowser

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator, GLib, Gtk

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_SECRETS_FILE = os.path.join(HERE, "client_secret.json")
TOKEN_FILE = os.path.join(HERE, "token.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
POLL_SECONDS = 60
MAX_POPUPS = 3  # more new messages than this get one summary popup
GMAIL_URL = "https://mail.google.com/"


def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if not creds.valid:
            try:
                creds.refresh(Request())
            except RefreshError:
                creds = None
    if creds is None:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(creds.to_json())
    return creds


def notify(title, body=""):
    subprocess.run(["notify-send", "-a", "Gmail", "-i", "mail-unread",
                    title, GLib.markup_escape_text(body)])


class App:
    def __init__(self):
        self.service = None
        self.seen = None  # unread ids already reported; None until first check
        self.busy = False

        self.indicator = AppIndicator.Indicator.new(
            "gmail-notify", "mail-read", AppIndicator.IndicatorCategory.COMMUNICATIONS)
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        menu = Gtk.Menu()
        for label, handler in (("Open Gmail", lambda: webbrowser.open(GMAIL_URL)),
                               ("Check now", self.check),
                               ("Quit", Gtk.main_quit)):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _item, h=handler: h())
            menu.append(item)
        menu.show_all()
        self.indicator.set_menu(menu)

        self.check()
        GLib.timeout_add_seconds(POLL_SECONDS, self.check)

    def check(self):
        if not self.busy:
            self.busy = True
            threading.Thread(target=self.poll, daemon=True).start()
        return True  # keep the timer running

    def poll(self):
        try:
            if self.service is None:
                self.service = build("gmail", "v1", credentials=get_credentials(),
                                     cache_discovery=False)
            users = self.service.users()
            unread = users.labels().get(userId="me", id="INBOX").execute()["messagesUnread"]
            ids = {m["id"] for m in users.messages().list(
                userId="me", q="is:unread in:inbox").execute().get("messages", [])}

            if self.seen is None:
                if unread:
                    notify(f"{unread} unread message(s)")
            else:
                new = ids - self.seen
                if len(new) > MAX_POPUPS:
                    notify(f"{len(new)} new messages")
                else:
                    for msg_id in new:
                        msg = users.messages().get(userId="me", id=msg_id, format="metadata",
                                                   metadataHeaders=["From", "Subject"]).execute()
                        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
                        notify(headers.get("Subject", "(no subject)"), headers.get("From", ""))
            self.seen = ids
            GLib.idle_add(self.show, "mail-unread" if unread else "mail-read",
                          str(unread) if unread else "")
        except Exception as e:  # network/auth failures: show warning, retry next poll
            print(f"gmail-notify: {e}", file=sys.stderr)
            if isinstance(e, RefreshError):
                self.service = None  # next poll re-runs the browser login
            GLib.idle_add(self.show, "dialog-warning", "")
        finally:
            self.busy = False

    def show(self, icon, label):
        self.indicator.set_icon_full(icon, label or "Gmail")
        self.indicator.set_label(label, "999")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = App()
    Gtk.main()
