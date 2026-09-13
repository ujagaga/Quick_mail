# Quick Mail

Quick Mail is a small Flask service that lets devices and scripts send plain-text email through HTTP requests. It uses an SMTP account for delivery, Google sign-in for the web interface, and SQLite to store accounts, device tokens, and recipient history.

## Features

- Send email using token-authenticated GET or POST requests.
- Send to multiple comma-separated recipients.
- Sign in with Google to view your device token after administrator approval.
- Manage account roles, delete users, view recipient counts, and reset recipient histories on `/admin`.
- Limit each account to 10 distinct recipients between administrator resets.
- Enforce a minimum two-minute delay between sending requests from the same account.
- Generate UUIDv4 device tokens with database-enforced uniqueness and collision retries.

## Install dependencies

Use Python 3.9 or newer with pip, virtual environment support, and SQLite support. Run these commands from the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.py.example config.py
```

On Windows, activate with `.venv\Scripts\activate` and copy the configuration with `copy config.py.example config.py`.

The standard installation includes Flask, Authlib, requests, and the dependencies listed in `requirements.txt`. SQLite and SMTP support come from Python's standard library. Pillow and captcha are not required.

For CGI hosts where Authlib's `cryptography` dependency cannot be installed, use the manual OAuth client with this smaller dependency installation:

```bash
python -m pip install Flask==3.1.0 requests
```

Set `USE_MANUAL_OAUTH = True` for that option. The manual client stores its access token on a shared client instance and is intended for CGI's process-per-request model. Use Authlib (`USE_MANUAL_OAUTH = False`) for concurrent WSGI hosting.

## Configuration

Edit `config.py` before starting:

| Setting | Purpose |
| --- | --- |
| `SMTP_SERVER` | SMTP server hostname. |
| `SMTP_PORT` | SMTP port; the example uses `587`. |
| `SMTP_USER` | SMTP login and sender email address. |
| `SMTP_PASS` | SMTP password. |
| `ADMIN_EMAIL` | Initial administrator's Google account email; receives signup notifications. |
| `DB_FILE` | SQLite database path; `users.db` by default, relative to the working directory. |
| `CLIENT_SECRETS_FILE` | Google OAuth client JSON file, resolved relative to `index.py` unless absolute. |
| `USE_MANUAL_OAUTH` | `False` for Authlib, or `True` for the included requests-based OAuth client. |
| `FLASK_APP_SECRET_KEY` | Private random secret used to sign browser sessions. |
| `MIN_WAIT_TIME` | Per-account sending delay in seconds; values below `120` are raised to `120`. |

The current mail helper authenticates over plain SMTP without STARTTLS or implicit TLS. Providers requiring TLS will not work with it, even on port `587`. Use a suitable trusted relay or add TLS support to the helper for those providers.

### Google sign-in

Provide a Google OAuth client for a web application. Save the downloaded JSON as `client_secret.json` beside `index.py`, or configure its path. The JSON must include the top-level `web` object with the client credentials and OAuth endpoint URLs.

Register the exact callback URL for the deployment, for example:

```text
https://quickmail.example.com/oauth2callback
```

The application builds the callback from the incoming request's scheme and host, so the hosting setup must expose the correct public URL. Google sign-in requires a valid client secrets file.
Keep the configuration, OAuth credentials, database, and device tokens private. They should not be committed.

## Run locally

With the virtual environment active, run from the project directory:

```bash
python index.py
```

Open `http://127.0.0.1:5000`. This starts Flask's development server with debug mode enabled.


### First run and account approval

1. Running `index.py` initializes the database. Under WSGI/CGI, initialization happens on the first request. The app creates the initial administrator using `ADMIN_EMAIL` and attempts to email their token.
2. Sign in with the Google account matching `ADMIN_EMAIL`. The home page displays your token; `/admin` provides user administration.
3. Other Google sign-ins create pending accounts and trigger an administrator notification. Pending accounts cannot use the sending API.
4. Change a pending user's role to `guest` to approve them and email their token. The `admin` role also allows user management.
5. Wait at least `MIN_WAIT_TIME` (120 seconds) after account creation, a role change, or the previous sending request before sending again.

The process needs write access to the database and its parent directory. Back up the database to preserve accounts, tokens, and recipient histories. Changing `ADMIN_EMAIL` does not replace the administrator in an existing database.

## Sending email

Send a request to `/send` with all four parameters:

| Parameter | Value |
| --- | --- |
| `token` | An approved user's device token. |
| `to` | One email address or multiple comma-separated addresses. |
| `sub` | Email subject. |
| `msg` | Plain-text message body. |

Messages are plain text; HTML is not rendered and attachments are not supported. No browser login is needed for this endpoint: the token authenticates the request.

### POST

POST accepts form fields, not JSON. Replace the hostname, token, and recipient:

```bash
curl 'https://quickmail.example.com/send' \
  --data-urlencode 'token=YOUR_DEVICE_TOKEN' \
  --data-urlencode 'to=recipient@example.com' \
  --data-urlencode 'sub=Device status' \
  --data-urlencode 'msg=Your device is online.'
```

### GET

```bash
curl --get 'https://quickmail.example.com/send' \
  --data-urlencode 'token=YOUR_DEVICE_TOKEN' \
  --data-urlencode 'to=first@example.com,second@example.com' \
  --data-urlencode 'sub=Device status' \
  --data-urlencode 'msg=Your device is online.'
```

URL-encode values as shown. Prefer POST to keep the token and message out of the URL and ordinary URL access logs.

### Responses

| HTTP status | Meaning |
| --- | --- |
| `200` | `OK`, optionally followed by malformed recipient addresses that were skipped. |
| `400` | Missing message, recipient, or subject; or no valid recipients. |
| `401` | Missing or unknown token, including tokens belonging to pending accounts. |
| `403` | The request would exceed the account's 10-recipient limit; no email is sent. |
| `406` | The account must wait before sending again; the response includes remaining seconds. |

SMTP errors are printed to server output rather than returned to the caller, so `OK` does not guarantee delivery. Check server logs when diagnosing missing messages.

The sending delay applies across all recipients for an account. Once all required fields are present, the sending timestamp is updated before recipient validation and limit checks. Requests with invalid addresses, requests exceeding the recipient limit, and failed SMTP attempts can therefore trigger the cooldown.

## Recipient limits and resets

Each account may use **10 distinct recipient addresses** between administrator resets. SQLite stores the addresses case-insensitively. Duplicate addresses in a request receive only one email.

After all 10 slots are used, the account can still send to previously used addresses. A request containing new valid addresses that would exceed the limit is refused entirely before sending or adding any recipients. Database transactions prevent concurrent sending requests from exceeding the cap. Addresses are reserved before SMTP delivery, so failed delivery attempts still consume slots.

The `/admin` users page displays each account's count, such as `3 / 10`. The small reset icon beside it, labelled **Reset recipients**, clears that account's list and restores all 10 slots. Only administrators can reset histories. Resetting preserves the account's token, role, and sending cooldown. Deleting an account also deletes its recipient history.


## Hosting

### WSGI

The entry point is `index:app`. Configure the host to use the project's Python environment and working directory. For providers requiring a Python entry file:

```python
from index import app as application
```

Use HTTPS and the public OAuth callback. Serve the application at the domain root because links and redirects use root-relative paths such as `/login`, `/admin`, and `/send`. Use Authlib for concurrent WSGI hosting.
