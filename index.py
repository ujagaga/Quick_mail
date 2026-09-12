#!/usr/bin/env python3
import os
from flask import Flask, request, render_template, flash, redirect, abort, session
from config import (ADMIN_EMAIL, FLASK_APP_SECRET_KEY, MAX_RECIPIENT_HISTORY, MIN_TIMEOUT, CLIENT_SECRETS_FILE,
                    USE_MANUAL_OAUTH)
from helper import (send_email, generate_token, is_valid_email, init_db, get_user_from_db,
                    add_user, delete_user, update_user)
import json
from time import time

app = Flask(__name__)
# app.config["APPLICATION_ROOT"] = "/cgi-bin/cgi_serve.py"
app.config['SECRET_KEY'] = FLASK_APP_SECRET_KEY
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

google = None
client_secrets_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CLIENT_SECRETS_FILE)
if os.path.isfile(client_secrets_path):
    try:
        if USE_MANUAL_OAUTH:
            from manual_oauth import ManualGoogleOAuth
            google = ManualGoogleOAuth(client_secrets_path)
        else:
            from authlib.integrations.flask_client import OAuth

            with open(client_secrets_path) as f:
                client_secrets = json.load(f)['web']

            oauth = OAuth(app)
            google = oauth.register(
                name='google',
                client_id=client_secrets['client_id'],
                client_secret=client_secrets['client_secret'],
                access_token_url=client_secrets['token_uri'],
                authorize_url=client_secrets['auth_uri'],
                api_base_url='https://www.googleapis.com/oauth2/v1/',
                userinfo_endpoint='https://www.googleapis.com/oauth2/v3/userinfo',
                client_kwargs={'scope': 'email'},
                server_metadata_url='https://accounts.google.com/.well-known/openid-configuration'
            )
    except Exception as e:
        print(f"Failed to register Google OAuth: {e}")


def check_auth():
    email = session.get('email')
    if email:
        user = get_user_from_db(email=email)
        if user and user['status'] != 'pending':
            return user

    return None


@app.before_request
def check_token():
    init_db()
    excluded_routes = ['home', 'login', 'authorize', 'oauth2callback', 'static', 'send']  # Add routes to exclude
    if request.endpoint in excluded_routes:
        return  # Skip checking the session

    if not check_auth():
        return redirect(f"/login?next_url={request.endpoint}")


@app.route("/login", methods=["GET"])
def login():
    next_url = request.args.get('next_url')
    return render_template('login.html', hide_nav=True, next_url=next_url)


@app.route("/authorize", methods=["GET"])
def authorize():
    next_url = request.args.get('next_url')
    if next_url and next_url != 'None':
        session['next_url'] = next_url

    redirect_uri = f"{request.host_url}oauth2callback"
    return google.authorize_redirect(redirect_uri)


@app.route("/oauth2callback", methods=["GET"])
def oauth2callback():
    google.authorize_access_token()
    email = google.get('userinfo').json()['email']

    user = get_user_from_db(email=email)
    if not user:
        token = generate_token()
        add_user(email, token)
        send_email(
            recipient=ADMIN_EMAIL,
            subject="New user signed up",
            body=f"New user: {email} signed up for quick mail service."
                 f"\nApprove or remove: {request.host_url}admin"
        )
        flash("Account created. You will be contacted by the administrator as soon as possible.")
        return redirect('/login')

    if user['status'] == 'pending':
        flash("Your account is still awaiting administrator approval.")
        return redirect('/login')

    session['email'] = email
    next_url = session.pop('next_url', None)
    target_url = f"/{next_url}" if next_url and next_url != 'None' else "/"

    return redirect(target_url)


@app.route("/logout", methods=["GET"])
def logout():
    session.clear()
    return redirect('/')


@app.route("/", methods=["GET"])
def home():
    user = check_auth()
    return render_template('home.html', authorized=bool(user), user=user)


@app.route("/send", methods=["GET", "POST"])
def send():
    # Get parameters from request
    data = request.args if request.method == "GET" else request.form
    token, msg, recipient, subject = data.get("token"), data.get("msg"), data.get("to"), data.get("sub", "")

    if not token:
        abort(401, description="Missing token parameter")

    user = get_user_from_db(token=token)
    if not user:
        abort(401, description="Provided token was not found in our records.")

    last_timestamp = int(user["timestamp"])
    time_since_last_mail = time() - last_timestamp
    if time_since_last_mail < MIN_TIMEOUT:
        abort(406, description=f"Please wait another {int(MIN_TIMEOUT - time_since_last_mail)}s before trying again")

    if not msg:
        abort(400, description='Missing message to email as "msg" parameter')

    # Load allowed recipients
    try:
        allowed_recipients = json.loads(user.get("recipients", "[]"))
    except (json.JSONDecodeError, TypeError):
        allowed_recipients = []

    # Process recipients
    accepted_recipients, rejected_recipients = [], []
    requested_recipients = [r.strip() for r in recipient.split(",")] if recipient else allowed_recipients

    for r in requested_recipients:
        if not is_valid_email(r):
            rejected_recipients.append(r)
        elif r in allowed_recipients or len(allowed_recipients) < MAX_RECIPIENT_HISTORY:
            accepted_recipients.append(r)
            if r not in allowed_recipients:
                allowed_recipients.append(r)
        else:
            rejected_recipients.append(r)

    update_user(user["email"], recipients=json.dumps(allowed_recipients))

    if not accepted_recipients:
        abort(400, description=f"No valid recipients found. Rejected: {json.dumps(rejected_recipients)}")

    # Send emails
    for r in accepted_recipients:
        send_email(recipient=r, subject=subject, body=msg)

    # Response message
    ret_message = "OK"
    if rejected_recipients:
        ret_message += f". Some recipients were rejected: {json.dumps(rejected_recipients)}. They are either malformed or exceeded the {MAX_RECIPIENT_HISTORY} limit."

    return ret_message


@app.route("/admin", methods=["GET"])
def admin():
    administrator = check_auth()

    if not administrator or administrator['status'] != 'admin':
        return redirect('/login')

    email = request.args.get('email')
    command = request.args.get('cmd')

    if email and command:
        if command == 'd':
            delete_user(email)
        else:
            update_user(email, status='approved')
            user = get_user_from_db(email=email)
            body = (f"You have been approved for using Quick Mail service."
                    f"\nYour token is: {user['token']}"
                    f"\nYou may now log in at {request.host_url}login with your Google account."
                    f"\n\nTo send an e-mail, you can use the following URL example:\n"
                    f'{request.host_url}send?token={user["token"]}&msg="Some test message"&to={email}&sub="Test mail subject"'
                    f"\n\nYou can also use a POST request with parameters in the request body."
                    f"\nOnce you send an e-mail, the recipient will be added to your recipient list. "
                    f'Up to {MAX_RECIPIENT_HISTORY} recipients will be saved, so if you omit the "to" parameter,'
                    f'the recipient list will be populated from the history. While this simplifies sending mail for you, '
                    f'it also prevents bots from using this service to spam a large number of e-mail addresses.'
                    )
            send_email(
                recipient=email,
                subject="Approved for Quick Mail",
                body=body
            )

        return redirect('/admin')

    users = get_user_from_db(exclude=administrator['email'])
    return render_template('admin.html', authorized=True, users=users)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
