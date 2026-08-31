#!/usr/bin/env python3
"""
Lakeland TN Custom News Digest - Mailer
Dispatches multipart (HTML + Plain Text) emails via SMTP (Gmail, Outlook, SendGrid, etc.).
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime


def load_env_file(dotenv_path: str = ".env"):
    """Lightweight .env loader without requiring external libraries."""
    if not os.path.exists(dotenv_path):
        return
    with open(dotenv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val


def send_digest_email(html_body: str, plain_text_body: str, article_count: int) -> bool:
    """Sends the news digest email using configured SMTP environment variables."""
    load_env_file()

    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS") or os.environ.get("SMTP_PASSWORD", "")
    sender_email = os.environ.get("SENDER_EMAIL") or smtp_user
    sender_name = os.environ.get("SENDER_NAME", "Lakeland News Digest")
    recipient_email = os.environ.get("RECIPIENT_EMAIL", "")

    if not smtp_user or not smtp_pass or not recipient_email:
        print("❌ Error: Missing SMTP credentials in environment variables or .env file.", flush=True)
        print("Required: SMTP_USER, SMTP_PASS, RECIPIENT_EMAIL", flush=True)
        return False

    today_str = datetime.now().strftime("%b %d, %Y")
    subject = f"📬 Lakeland, TN News Digest ({today_str}) - {article_count} Updates"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, sender_email))
    msg["To"] = recipient_email

    # Attach plain text fallback and HTML versions
    part1 = MIMEText(plain_text_body, "plain", "utf-8")
    part2 = MIMEText(html_body, "html", "utf-8")
    msg.attach(part1)
    msg.attach(part2)

    try:
        print(f"Connecting to SMTP server {smtp_host}:{smtp_port}...")
        if smtp_port == 465:
            # SSL
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(sender_email, [recipient_email], msg.as_string())
        else:
            # STARTTLS (default for port 587)
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.sendmail(sender_email, [recipient_email], msg.as_string())

        print(f"✅ News digest successfully emailed to {recipient_email}!")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}", flush=True)
        return False
