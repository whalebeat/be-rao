"""Admin notification email via SMTP. Without SMTP settings it only logs."""
import smtplib
from email.message import EmailMessage

from flask import current_app

from . import env


def send_admin_mail(subject, body):
    from .settings import get_setting
    to = env('ADMIN_EMAIL') or get_setting('admin_email')
    host = env('SMTP_HOST')
    if not to or not host:
        current_app.logger.info('Mail not sent (no SMTP_HOST/ADMIN_EMAIL): %s', subject)
        return False
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = env('SMTP_FROM') or env('SMTP_USER') or to
    msg['To'] = to
    msg.set_content(body)
    port = int(env('SMTP_PORT', '587'))
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        with server:
            if env('SMTP_USER'):
                server.login(env('SMTP_USER'), env('SMTP_PASSWORD', ''))
            server.send_message(msg)
        return True
    except Exception as exc:  # never fail an order/lead because mail is down
        current_app.logger.warning('Mail failed (%s): %s', exc, subject)
        return False
