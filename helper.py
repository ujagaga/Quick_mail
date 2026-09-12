import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS, DB_FILE, ADMIN_EMAIL, MIN_WAIT_TIME as _CONFIGURED_MIN_WAIT_TIME
import sqlite3
import re
from time import time
import os
import uuid

MAX_RECIPIENTS = 10

MIN_WAIT_TIME = max(_CONFIGURED_MIN_WAIT_TIME, 120)  # enforce a 2min floor regardless of config

'''
Sends an email using configured credentials. 
'''
def send_email(recipient, subject, body):

    # Create message
    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Connect to SMTP server without SSL
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.ehlo()

        # Login to the SMTP server
        server.login(SMTP_USER, SMTP_PASS)

        # Send email
        server.sendmail(SMTP_USER, recipient, msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Error: {e}")


def generate_token():
    return str(uuid.uuid4())


def is_valid_email(email):
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email))


def init_recipient_history(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_recipients (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            recipient TEXT NOT NULL COLLATE NOCASE,
            PRIMARY KEY (user_id, recipient)
        )
    """)


def reserve_recipients(user_id, recipients):
    """Reserve the entire batch before SMTP, including failed delivery attempts.

    The write lock prevents concurrent requests from exceeding the account limit.
    """
    recipients = {recipient.strip().lower() for recipient in recipients}
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('BEGIN IMMEDIATE')
        existing = {row[0] for row in conn.execute(
            'SELECT recipient FROM user_recipients WHERE user_id = ?', (user_id,)
        )}
        if len(existing | recipients) > MAX_RECIPIENTS:
            return False
        conn.executemany(
            'INSERT INTO user_recipients (user_id, recipient) VALUES (?, ?)',
            [(user_id, recipient) for recipient in recipients - existing],
        )
    return True


def reset_recipients(email):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            'DELETE FROM user_recipients WHERE user_id = (SELECT id FROM users WHERE email = ?)',
            (email,),
        )


def init_db():
    if os.path.exists(DB_FILE):
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('BEGIN IMMEDIATE')
            init_recipient_history(conn)
            columns = {row[1] for row in conn.execute('PRAGMA table_info(users)')}
            if 'picture_url' not in columns:
                conn.execute('ALTER TABLE users ADD COLUMN picture_url TEXT')
        return

    try:
        with sqlite3.connect(DB_FILE) as conn:
            create_table_sql_query = """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    token TEXT,
                    timestamp INTEGER,
                    picture_url TEXT
                )
            """
            cursor = conn.cursor()
            cursor.execute(create_table_sql_query)
            init_recipient_history(conn)
            conn.commit()

            token = generate_token()
            add_admin_sql_query = f"INSERT INTO users (email, status, token, timestamp) VALUES ('{ADMIN_EMAIL}', 'admin', '{token}', '{int(time())}')"
            cursor.execute(add_admin_sql_query)

            conn.commit()

            body = (f"You have been added as Admin of QuickMail service."
                    f"\nYour token is: {token}"
                    f"\n\nTo send an e-mail, you can use the following URL example:\n"
                    f'http://quickmail.yourdomain.com/send?token={token}&msg="Some test message"&to=recipient_email&sub="Test mail subject"'
                    f"\n\nYou can also use a POST request with parameters in the request body."
                    f'\nThe "to" and "sub" parameters are required.'
                    f"\nYou must wait at least {MIN_WAIT_TIME} seconds between emails."
                    )

            send_email(
                recipient=ADMIN_EMAIL,
                subject="Your Admin Credentials",
                body=body
            )
    except sqlite3.Error:
        pass


def get_user_from_db(email=None, token=None, exclude=None, include_pending=False):
    one = True
    if email:
        sql_query = "SELECT * FROM users WHERE email = ? AND status != 'pending'"
        if include_pending:
            sql_query = "SELECT * FROM users WHERE email = ?"
        params = (email,)
    elif token:
        sql_query = "SELECT * FROM users WHERE token = ? AND status != 'pending'"
        params = (token,)
    else:
        if exclude:
            sql_query = "SELECT * FROM users WHERE email != ?"
            params = (exclude,)
        else:
            sql_query = "SELECT * FROM users"
            params = ()
        one = False

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row  # Enables dictionary-like row access
        cursor = conn.cursor()
        sql_query = sql_query.replace(
            'SELECT * FROM users',
            'SELECT users.*, (SELECT COUNT(*) FROM user_recipients '
            'WHERE user_id = users.id) AS recipient_count FROM users',
            1,
        )
        cursor.execute(sql_query, params)

        if one:
            data = cursor.fetchone()
            return dict(data) if data else None  # Convert row to dict if found
        else:
            data = cursor.fetchall()
            return [dict(row) for row in data]  # Convert each row to dict


def add_user(email, token, picture_url=None):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (email, status, token, timestamp, picture_url) VALUES (?, ?, ?, ?, ?)",
                           (email, "pending", token, int(time()), picture_url))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            pass

    return False


def delete_user(email):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        conn.execute("PRAGMA foreign_keys = ON")
        cursor.execute("DELETE FROM users WHERE email = ?", (email,))
        conn.commit()


def update_user(email, status=None):
    timestamp = int(time())  # Get the current epoch time

    if status is not None:
        sql_query = f"UPDATE users SET status = '{status}', timestamp = {timestamp} WHERE email = '{email}'"
    else:
        sql_query = f"UPDATE users SET timestamp = {timestamp} WHERE email = '{email}'"

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(sql_query)
        conn.commit()

    return True


def update_user_picture(email, picture_url):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE users SET picture_url = ? WHERE email = ?", (picture_url, email))
