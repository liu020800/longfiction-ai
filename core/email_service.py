import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from core.config import settings

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

VERIFICATION_CODE_SUBJECT = "LongFiction-AI 邮箱验证码"
RESET_PASSWORD_SUBJECT = "LongFiction-AI 密码重置"


def is_smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)


def send_email(to: str, subject: str, body: str, html_body: str = None) -> bool:
    if not is_smtp_configured():
        logger.warning("SMTP not configured, email not sent")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to

        msg.attach(MIMEText(body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        if SMTP_USE_TLS:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)

        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, [to], msg.as_string())
        server.quit()
        logger.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")
        return False


def send_verification_code(to: str, code: str) -> bool:
    body = f"您的验证码是：{code}\n\n验证码5分钟内有效，请勿泄露给他人。\n\n— LongFiction-AI"
    html = f"""
    <div style="max-width:480px;margin:0 auto;padding:24px;font-family:sans-serif;">
      <h2 style="color:#4f46e5;">LongFiction-AI 邮箱验证</h2>
      <p>您的验证码是：</p>
      <div style="font-size:32px;font-weight:bold;letter-spacing:8px;color:#4f46e5;
                  background:#f3f4f6;padding:12px 20px;border-radius:8px;text-align:center;margin:16px 0;">
        {code}
      </div>
      <p style="color:#6b7280;font-size:13px;">验证码5分钟内有效，请勿泄露给他人。</p>
    </div>"""
    return send_email(to, VERIFICATION_CODE_SUBJECT, body, html)


def send_reset_password_link(to: str, reset_url: str) -> bool:
    body = f"点击以下链接重置密码：\n{reset_url}\n\n链接30分钟内有效。\n\n— LongFiction-AI"
    html = f"""
    <div style="max-width:480px;margin:0 auto;padding:24px;font-family:sans-serif;">
      <h2 style="color:#4f46e5;">LongFiction-AI 密码重置</h2>
      <p>点击以下按钮重置密码：</p>
      <a href="{reset_url}" style="display:inline-block;background:#4f46e5;color:#fff;
         padding:10px 24px;border-radius:6px;text-decoration:none;margin:16px 0;">
        重置密码
      </a>
      <p style="color:#6b7280;font-size:13px;">链接30分钟内有效。如非本人操作，请忽略此邮件。</p>
    </div>"""
    return send_email(RESET_PASSWORD_SUBJECT, body, html)
