import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS, DB_FILE, ADMIN_EMAIL, MAX_RECIPIENT_HISTORY
import sqlite3
import random
import string
import re
from time import time
import os
import hashlib

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


def md5_encode(string_data):
    """Encodes a string using MD5 and returns the hexadecimal digest.
    Args:
        string_data: The string to encode.  It will be encoded as UTF-8.
    Returns:
        The MD5 hash as a hexadecimal string, or None if an error occurs.
    """
    try:
        encoded_string = string_data.encode('utf-8')
        md5_hash = hashlib.md5()
        md5_hash.update(encoded_string)
        hex_digest = md5_hash.hexdigest()

        return hex_digest

    except Exception as e:
        print(f"Error during MD5 encoding: {e}")
        return None


def generate_token():
    random_str = random.choices(string.ascii_letters, k=16)
    unique_str = f"{random_str}{time()}"

    return md5_encode(unique_str)


def is_valid_email(email):
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email))


def init_db():
    if os.path.exists(DB_FILE):
        # Database file '{DB_FILE}' already exists. Aborting initialization.
        return

    try:
        with sqlite3.connect(DB_FILE) as conn:
            create_table_sql_query = """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    token TEXT,
                    recipients TEXT,
                    timestamp INTEGER
                )
            """
            cursor = conn.cursor()
            cursor.execute(create_table_sql_query)
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
                    f"\nOnce you send an e-mail, the recipient will be added to your recipient list. "
                    f'Up to {MAX_RECIPIENT_HISTORY} recipients will be saved, so if you omit the "to" parameter,'
                    f'the recipient list will be populated from the history. While this simplifies sending mail for you, '
                    f'it also prevents bots from using this service to spam a large number of e-mail addresses.'
                    )

            send_email(
                recipient=ADMIN_EMAIL,
                subject="Your Admin Credentials",
                body=body
            )
    except sqlite3.Error:
        pass


def get_user_from_db(email=None, token=None, exclude=None):
    one = True
    if email:
        sql_query = "SELECT * FROM users WHERE email = ? AND status != 'pending'"
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
        cursor.execute(sql_query, params)

        if one:
            data = cursor.fetchone()
            return dict(data) if data else None  # Convert row to dict if found
        else:
            data = cursor.fetchall()
            return [dict(row) for row in data]  # Convert each row to dict


def add_user(email, token):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (email, status, token, timestamp) VALUES (?, ?, ?, ?)",
                           (email, "pending", token, int(time())))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            pass

    return False


def delete_user(email):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM users WHERE email = '{email}'")
        conn.commit()


def update_user(email, status=None, recipients=None):
    timestamp = int(time())  # Get the current epoch time

    if status is not None and recipients is not None:
        sql_query = f"UPDATE users SET status = '{status}', recipients = '{recipients}', timestamp = {timestamp} WHERE email = '{email}'"
    elif status is not None:
        sql_query = f"UPDATE users SET status = '{status}', timestamp = {timestamp} WHERE email = '{email}'"
    elif recipients is not None:
        sql_query = f"UPDATE users SET recipients = '{recipients}', timestamp = {timestamp} WHERE email = '{email}'"
    else:
        return False

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(sql_query)
        conn.commit()

    return True
