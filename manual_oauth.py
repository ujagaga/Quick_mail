"""
Minimal hand-rolled Google OAuth2 client, used instead of Authlib when
USE_MANUAL_OAUTH is set in config.py. Only needs "requests" (pure Python,
no compiled dependencies), unlike Authlib which hard-requires "cryptography" -
a package with no prebuilt wheel on some hosts (e.g. FreeBSD shared hosting
where the C compiler is locked down).

Exposes the same subset of the Authlib client API index.py uses:
authorize_redirect(redirect_uri), authorize_access_token(), get('userinfo').
"""
import json
import secrets
from urllib.parse import urlencode
import requests
from flask import request, redirect, session, abort

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


class _Response:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class ManualGoogleOAuth:
    def __init__(self, client_secrets_path):
        with open(client_secrets_path) as f:
            client_secrets = json.load(f)['web']
        self.client_id = client_secrets['client_id']
        self.client_secret = client_secrets['client_secret']
        self._access_token = None  # single process per request under CGI, so this is safe

    def authorize_redirect(self, redirect_uri):
        state = secrets.token_urlsafe(24)
        session['oauth_state'] = state
        session['oauth_redirect_uri'] = redirect_uri

        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "email",
            "state": state,
        }
        return redirect(f"{AUTH_URL}?{urlencode(params)}")

    def authorize_access_token(self):
        if request.args.get('state') != session.pop('oauth_state', None):
            abort(401, description="Invalid OAuth state")

        code = request.args.get('code')
        redirect_uri = session.pop('oauth_redirect_uri', None)

        resp = requests.post(TOKEN_URL, data={
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        resp.raise_for_status()
        token = resp.json()
        self._access_token = token['access_token']
        return token

    def get(self, endpoint):
        if endpoint != 'userinfo':
            raise ValueError(f"Unsupported endpoint: {endpoint}")

        resp = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {self._access_token}"})
        resp.raise_for_status()
        return _Response(resp.json())
