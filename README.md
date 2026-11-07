# Gmail Notify

Tray icon for Linux desktops that checks the signed-in Gmail account for unread inbox mail and shows desktop notifications (freedesktop notifications via `notify-send`).

- Polls every 60 seconds (`POLL_SECONDS` in `gmail_notify.py`).
- Tray icon shows the unread inbox count; a warning icon means the last check failed (details on stderr).
- One popup per new message (subject + sender); more than 3 new messages at once get one summary popup.
- Tray menu: Open Gmail, Check now, Quit.
- Read-only access (`gmail.readonly` scope).

## System requirements

Python 3.9+, GTK 3 and Ayatana AppIndicator GObject bindings, and `notify-send`. On Debian/Ubuntu:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 libnotify-bin
```

The desktop panel must support AppIndicator/StatusNotifier icons (XFCE: Indicator Plugin or Status Tray Plugin).

## Install

```bash
./install.sh
```

This creates `.venv` with access to the system `gi` package and installs `requirements.txt`. It is safe to re-run; it also repairs a venv created without system site packages.

## Google OAuth client

1. In Google Cloud Console, enable the **Gmail API** for your project.
2. Under **APIs & Services > Credentials**, create an OAuth client ID of type **Desktop app**. A Web application client will not work.
3. Download its JSON and save it as `client_secret.json` beside `gmail_notify.py`.
4. On the OAuth consent screen, add your Gmail address as a test user.

While the consent screen's publishing status is **Testing**, Google expires refresh tokens after 7 days, so the browser login reappears weekly. Setting the status to **In production** avoids that; for personal use Google shows an "unverified app" warning you can click through.

## Run

```bash
./run.sh
```

The first run opens a browser for Google sign-in and stores the token in `token.json` (mode 600). If the token is later revoked or expires, the next check opens the browser again.

To start on login in XFCE, add an entry in **Session and Startup > Application Autostart** with the command:

```text
/path/to/Quick_mail/run.sh
```

Keep `client_secret.json` and `token.json` private; both are git-ignored.
