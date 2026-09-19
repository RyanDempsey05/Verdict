import os

import httpx

API_URL = "https://api.resend.com/emails"
_key = os.environ.get("RESEND_API_KEY", "")
_from = os.environ.get("MAIL_FROM", "Verdict <noreply@verdictapp.app>")

# the VM's IPv6 route is dead on NAT; force IPv4 so sends don't hang
_transport = httpx.HTTPTransport(local_address="0.0.0.0")


def send(to: str, subject: str, text: str, html: str | None = None) -> bool:
    if not _key:
        return False

    payload = {"from": _from, "to": [to], "subject": subject, "text": text}
    if html:
        payload["html"] = html

    try:
        with httpx.Client(timeout=10.0, transport=_transport) as client:
            resp = client.post(
                API_URL,
                headers={"Authorization": f"Bearer {_key}"},
                json=payload,
            )
            resp.raise_for_status()
        return True
    except Exception:
        return False


def send_password_reset(to: str, username: str, link: str) -> bool:
    text = (
        f"Hi {username},\n\n"
        f"Someone asked to reset the password on your Verdict account. "
        f"Open this link within the next hour to choose a new one:\n\n"
        f"{link}\n\n"
        f"If this wasn't you, you can ignore this email and nothing will change.\n\n"
        f"— Verdict\nverdictapp.app"
    )
    html = f"""<!DOCTYPE html>
<html><body style="margin:0;padding:32px 16px;background:#0a0a0b;font-family:Helvetica,Arial,sans-serif">
  <div style="max-width:520px;margin:0 auto;background:#121214;border:1px solid #26262a;border-radius:4px;padding:32px">
    <div style="font-size:22px;letter-spacing:.18em;color:#ededf0;margin-bottom:24px">
      VER<span style="color:#e0394d">DICT</span>
    </div>
    <p style="color:#d2d2d7;font-size:15px;line-height:1.6;margin:0 0 16px">Hi {username},</p>
    <p style="color:#d2d2d7;font-size:15px;line-height:1.6;margin:0 0 24px">
      Someone asked to reset the password on your account. Choose a new one within the next hour.
    </p>
    <a href="{link}" style="display:inline-block;background:#c42638;color:#f2eaea;text-decoration:none;padding:12px 28px;border-radius:3px;font-size:14px;font-weight:600">
      Reset password
    </a>
    <p style="color:#76767e;font-size:13px;line-height:1.6;margin:28px 0 0">
      If this wasn't you, ignore this email and nothing will change.
    </p>
    <p style="color:#4a4a52;font-size:12px;margin:24px 0 0">verdictapp.app</p>
  </div>
</body></html>"""
    return send(to, "Reset your Verdict password", text, html)
