# Quick Mail

A simple service to help low-end devices to sends e-mail.
It is free to use with a limitation of default 10 recipient e-mail addresses for one account.
This is to prevent bots from spamming. If you need to reset the recipient history, there is a page for it.

You can find a running service at:

        http://quickmail.ujagaga.in.rs

## How to start

Install required python libraries:

        pip install flask pillow captcha
        
Rename config.py.example to config.py and edit necessary variables.
At first start, the admin user will be added to the database and an email sent to notify of the generated token.

## Sending an e-mail using HTTP GET request

To send an e-mail, just make a request at url of the app with parameters:

        http://<quickmail_url>/send?token=<your_user_token>&msg=<"HTML_safe_text_message"&to=<recipient_email>

## Running on a cgi based hosting

On your local machine you could run:

        python3 index.py

but on a cgi based hosting service, you would set up a python app via cpanel.
If the cpanel is not available, you would need to provide cgi_serve.py which is included here. 
A common pitfall is that this script must be executable, so:

        chmod +x cgi_serve.py

## TODO

- Make sure token is unique

## Recipient limits and resets

Each account can use up to **10 distinct recipient addresses** between administrator resets. Addresses are stored in SQLite and counted case-insensitively. Repeated addresses in the same request receive only one email.

Once all 10 slots are used, previously used recipients remain allowed. A GET or form POST request to `/send` that would exceed the limit returns HTTP `403` before sending any emails or adding any recipients from that request. This also applies to multi-recipient requests and concurrent requests. Failed SMTP delivery attempts retain their recipient slots.

The `/admin` users page shows each account's recipient count (for example, `3 / 10`). Its **Reset recipients** button clears that account's stored list and restores all 10 slots. Only administrators can reset recipients; the account's token, role, and sending cooldown are preserved.

Existing databases are upgraded automatically. Recipient history starts empty because older versions did not record recipients. Deleting an account also deletes its recipient history.

Run the recipient tests with:

```bash
python3 -m unittest discover -s tests -v
```
