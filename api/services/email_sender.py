"""Transactional email delivery for account recovery."""

import html
import os

from azure.communication.email import EmailClient


def send_password_reset_email(recipient: str, reset_link: str) -> None:
    """Send a password reset message through Azure Communication Services."""
    connection_string = os.getenv("ACS_EMAIL_CONNECTION_STRING", "").strip()
    sender = os.getenv("ACS_SENDER_EMAIL", "").strip()
    if not connection_string or not sender:
        raise RuntimeError(
            "ACS_EMAIL_CONNECTION_STRING and ACS_SENDER_EMAIL must be configured"
        )

    safe_link = html.escape(reset_link, quote=True)
    message = {
        "senderAddress": sender,
        "recipients": {"to": [{"address": recipient}]},
        "content": {
            "subject": "Reset your AnalyzeMyCV password",
            "plainText": (
                "Use this link to reset your AnalyzeMyCV password. "
                "The link expires in 30 minutes and can be used once:\n\n"
                f"{reset_link}\n\nIf you did not request this, you can ignore this email."
            ),
            "html": (
                "<p>Use the link below to reset your AnalyzeMyCV password.</p>"
                "<p>This link expires in 30 minutes and can be used once.</p>"
                f'<p><a href="{safe_link}">Reset password</a></p>'
                "<p>If you did not request this, you can ignore this email.</p>"
            ),
        },
    }
    poller = EmailClient.from_connection_string(connection_string).begin_send(message)
    result = poller.result()
    if result.get("status") != "Succeeded":
        raise RuntimeError(f"Password reset email failed: {result}")
