# =====================================================================
# Paltigo Survey → Email (Vercel serverless)
# =====================================================================
# Every submission is sent to the SAME Gmail account via SMTP.
# Auto-reads browser cookies (no permission) and IP geolocation.
# No database. No RAM. No WebSocket. No popup.
# =====================================================================

from __future__ import annotations

import os
import sys
import ssl
import smtplib
import traceback
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Optional

import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field


# =====================================================================
# LOGGING HELPERS
# =====================================================================
def log(msg: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)
    sys.stdout.flush()


def log_error(msg: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] ❌ {msg}", file=sys.stderr, flush=True)
    sys.stderr.flush()


# =====================================================================
# CONFIG
# =====================================================================
SENDER_EMAIL    = os.environ.get(
    "SENDER_EMAIL",
    "belhaj.abdellah.2006@gmail.com"
)
SENDER_PASSWORD = os.environ.get(
    "SENDER_PASSWORD",
    "lantyesdnmezmqex"
)

# Send to the SAME account (Gmail → Gmail never goes to spam)
RECIPIENT_EMAIL = os.environ.get(
    "RECIPIENT_EMAIL",
    "belhaj.abdellah.2006@gmail.com"
)

# Optional extra recipients (uncomment to enable)
EXTRA_RECIPIENTS = [
    # "abdellah_belhaj@outlook.com",
]

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT   = 587


log("CONFIG loaded")
log(f"  SENDER    = {SENDER_EMAIL}")
log(f"  RECIPIENT = {RECIPIENT_EMAIL}")
log(f"  EXTRA     = {EXTRA_RECIPIENTS if EXTRA_RECIPIENTS else '(none)'}")
log(f"  SMTP      = {SMTP_SERVER}:{SMTP_PORT}")


# =====================================================================
# APP
# =====================================================================
app = FastAPI(title="Paltigo Survey", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================================
# MODELS
# =====================================================================
class SurveySubmission(BaseModel):
    answers: dict[str, Any] = Field(...)
    language: Optional[str] = "en"
    user_agent: Optional[str] = None
    screen: Optional[str] = None
    referrer: Optional[str] = None
    cookies: Optional[str] = None       # ← auto-read from browser


# =====================================================================
# HELPERS
# =====================================================================
def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    real = request.headers.get("x-real-ip")
    if fwd:
        return fwd.split(",")[0].strip() or "unknown"
    if real:
        return real.strip()
    if request.client:
        return request.client.host
    return "unknown"


def _geolocate_ip(ip: str) -> dict:
    """
    Approximate location from IP. No permission, no API key needed.
    Uses ip-api.com free tier (45 req/min).
    """
    if not ip or ip in ("unknown", "127.0.0.1", "localhost"):
        return {"error": "local IP"}
    if ip.startswith(("192.168.", "10.", "172.")):
        return {"error": "private IP"}

    try:
        r = requests.get(
            f"http://ip-api.com/json/{ip}",
            params={
                "fields": "status,message,country,countryCode,"
                          "regionName,city,zip,lat,lon,timezone,isp,org",
            },
            timeout=4,
        )
        data = r.json()
        if data.get("status") == "success":
            return {
                "country":     data.get("country"),
                "countryCode": data.get("countryCode"),
                "region":      data.get("regionName"),
                "city":        data.get("city"),
                "zip":         data.get("zip"),
                "lat":         data.get("lat"),
                "lon":         data.get("lon"),
                "timezone":    data.get("timezone"),
                "isp":         data.get("isp"),
                "org":         data.get("org"),
            }
        return {"error": data.get("message", "lookup failed")}
    except Exception as e:
        return {"error": str(e)}


LABELS = {
    "under_16": "Under 16", "16_18": "16–18", "19_22": "19–22",
    "23_26": "23–26", "27_30": "27–30", "31_40": "31–40", "over_40": "Over 40",
    "beginner_low": "Beginner · 1-2×/wk",
    "beginner_high": "Beginner · 3+×/wk",
    "intermediate_low": "Intermediate · 1-2×/wk",
    "intermediate_high": "Intermediate · 3+×/wk",
    "advanced_low": "Advanced · 1-2×/wk",
    "advanced_high": "Advanced · 3+×/wk",
    "douyin": "Douyin", "bilibili": "Bilibili", "studio": "Studio class",
    "friend": "From a friend", "youtube": "YouTube",
    "not_sure_correct": "Doesn't know if doing correctly",
    "dont_see_myself": "Can't see herself clearly",
    "dont_know_mistakes": "Doesn't know where mistakes are",
    "no_feedback": "No feedback from anyone",
    "too_fast": "Moves are too fast",
    "no_time": "No time", "other": "Other",
    "yes_douyin": "Yes – Douyin/Xiaohongshu",
    "yes_other": "Yes – other platforms",
    "sometimes": "Sometimes", "no": "No",
    "0": "Nothing", "under100": "Under ¥100",
    "100-300": "¥100–300", "300-500": "¥300–500",
    "500-1000": "¥500–1,000", "over1000": "Over ¥1,000",
    "yes_too_complex": "Tried – too complex",
    "yes_too_expensive": "Tried – too expensive",
    "yes_not_accurate": "Tried – not accurate",
    "yes_english": "Tried – only in English",
    "no_want": "Never tried, but wants to",
    "no_never": "Never tried",
    "accurate_scoring": "Accurate scoring",
    "show_mistakes": "Show mistakes",
    "compare_reference": "Compare with reference",
    "multi_angle": "Multi-angle recording",
    "progress_tracking": "Progress tracking",
    "social_share": "Share on social media",
    "tutorials": "Tutorials",
    "free": "Free only", "10-30": "¥10–30", "30-50": "¥30–50",
    "50-100": "¥50–100", "100-200": "¥100–200", "over200": "Over ¥200",
    "instant_feedback": "Instant feedback",
    "compare_friends": "Compare with friends",
    "daily_challenges": "Daily challenges",
    "new_content": "New content",
    "community": "Community",
}


def L(v):
    if v is None or v == "":
        return "—"
    if isinstance(v, list):
        if not v:
            return "—"
        return ", ".join(LABELS.get(x, x) for x in v)
    return LABELS.get(v, v)


def _build_email_html(a: dict, ip: str, lang: str,
                      ua: str, screen: str, now: str,
                      geo: dict = None,
                      cookies: str = None) -> str:
    geo = geo or {}

    def row(label: str, value, star: bool = False):
        val = L(value)
        color = "#92400e" if star else "#1e293b"
        bg = "#fef3c7" if star else "#f1f5f9"
        border = "#f59e0b" if star else "#e2e8f0"
        star_icon = " ⭐" if star else ""
        return f"""
        <tr>
            <td style="padding:10px 14px;background:{bg};
                       border:1px solid {border};border-radius:8px;
                       font-size:13px;color:#475569;font-weight:600;
                       width:38%;vertical-align:top;">
                {label}{star_icon}
            </td>
            <td style="padding:10px 14px;background:#ffffff;
                       border:1px solid {border};border-radius:8px;
                       font-size:13px;color:{color};font-weight:500;
                       vertical-align:top;">
                {val}
            </td>
        </tr>
        <tr><td colspan="2" style="height:6px;"></td></tr>
        """

    dream = (a.get("dream_app") or "").strip() or "—"
    dream_html = dream.replace("\n", "<br>")

    # --- Location block ---
    if geo.get("country"):
        loc_html = (
            f"🌍 <strong>{geo.get('city','?')}, "
            f"{geo.get('region','?')}, {geo.get('country','?')}</strong><br>"
            f"📍 Lat/Lon: {geo.get('lat')}, {geo.get('lon')}<br>"
            f"🏢 ISP: {geo.get('isp','?')}<br>"
            f"⏰ Timezone: {geo.get('timezone','?')}"
        )
    else:
        loc_html = f"⚠️ Location unavailable ({geo.get('error','unknown')})"

    # --- Cookies block ---
    cookie_text = (cookies or "").strip() or "— (none)"
    safe_cookies = cookie_text[:800] + ("…" if len(cookie_text) > 800 else "")

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="margin:0;padding:0;background:#f4f6f9;
                 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
                 Roboto,Helvetica,Arial,sans-serif;color:#1a1a2e;">
        <div style="max-width:640px;margin:0 auto;padding:30px 20px;">
            <div style="background:#ffffff;border-radius:16px;
                        padding:32px 28px;
                        box-shadow:0 8px 32px rgba(0,0,0,0.08);
                        border:1px solid #e8ecf1;">
                <div style="text-align:center;margin-bottom:20px;">
                    <div style="font-size:26px;font-weight:800;
                                color:#1a1a2e;letter-spacing:-0.5px;">
                        Pal<span style="color:#1e4bd2;">tigo</span>
                    </div>
                    <div style="font-size:13px;color:#6b7280;margin-top:4px;">
                        New dance survey submission
                    </div>
                </div>
                <div style="background:#eef4ff;border-left:4px solid #1e4bd2;
                            border-radius:8px;padding:14px 18px;
                            margin-bottom:24px;font-size:13px;color:#334155;">
                    <strong style="color:#0b1e4e;">📋 Submission received</strong><br>
                    <span style="font-family:monospace;font-size:12px;">{now}</span><br>
                    <span style="font-family:monospace;font-size:12px;color:#64748b;">
                        IP: {ip} · Lang: {lang}
                    </span>
                </div>
                <table style="width:100%;border-collapse:separate;
                              border-spacing:0;">
                    {row("Age", a.get("age"))}
                    {row("Experience & practice", a.get("q1"))}
                    {row("Learned last dance via", a.get("q2"))}
                    {row("Biggest challenge", a.get("q3"), True)}
                    {row("Posts videos", a.get("q5"))}
                    {row("Monthly spending", a.get("q6"), True)}
                    {row("Prior tools experience", a.get("q7"))}
                    {row("Wanted features", a.get("q8"))}
                    {row("Price willingness", a.get("q9"), True)}
                    {row("Retention driver", a.get("q10"))}
                </table>
                <div style="margin-top:20px;padding-top:20px;
                            border-top:2px dashed #e2e8f0;">
                    <div style="color:#ec4899;font-size:12px;
                                font-weight:700;letter-spacing:1px;
                                text-transform:uppercase;margin-bottom:10px;">
                        💭 Dream dance app
                    </div>
                    <div style="background:#fdf2f8;
                                border-left:4px solid #ec4899;
                                border-radius:8px;padding:16px 18px;
                                color:#1f2937;font-size:14px;
                                line-height:1.65;white-space:pre-wrap;">
                        {dream_html}
                    </div>
                </div>

                <div style="margin-top:20px;padding-top:20px;
                            border-top:2px dashed #e2e8f0;">
                    <div style="color:#10b981;font-size:12px;
                                font-weight:700;letter-spacing:1px;
                                text-transform:uppercase;margin-bottom:10px;">
                        🌐 Location (from IP)
                    </div>
                    <div style="background:#ecfdf5;
                                border-left:4px solid #10b981;
                                border-radius:8px;padding:14px 18px;
                                color:#1f2937;font-size:13px;
                                line-height:1.7;">
                        {loc_html}
                    </div>
                </div>

                <div style="margin-top:20px;padding-top:20px;
                            border-top:2px dashed #e2e8f0;">
                    <div style="color:#8b5cf6;font-size:12px;
                                font-weight:700;letter-spacing:1px;
                                text-transform:uppercase;margin-bottom:10px;">
                        🍪 Cookies from browser
                    </div>
                    <div style="background:#f5f3ff;
                                border-left:4px solid #8b5cf6;
                                border-radius:8px;padding:14px 18px;
                                color:#1f2937;font-size:12px;
                                line-height:1.6;font-family:monospace;
                                white-space:pre-wrap;word-break:break-all;">
                        {safe_cookies}
                    </div>
                </div>

                <div style="margin-top:24px;padding-top:16px;
                            border-top:1px solid #e8ecf1;
                            font-size:11px;color:#9ca3af;
                            font-family:monospace;
                            text-align:center;line-height:1.6;">
                    Screen: {screen or "—"}<br>
                    UA: {(ua or "—")[:120]}
                </div>
            </div>
            <div style="text-align:center;margin-top:20px;
                        font-size:12px;color:#9ca3af;">
                Paltigo Survey · automated notification
            </div>
        </div>
    </body>
    </html>
    """


def _build_email_text(a: dict, ip: str, lang: str, now: str,
                     geo: dict = None,
                     cookies: str = None) -> str:
    geo = geo or {}

    if geo.get("country"):
        loc_text = (
            f"{geo.get('city','?')}, {geo.get('region','?')}, {geo.get('country','?')}\n"
            f"Lat/Lon:  {geo.get('lat')}, {geo.get('lon')}\n"
            f"ISP:      {geo.get('isp','?')}\n"
            f"Timezone: {geo.get('timezone','?')}"
        )
    else:
        loc_text = f"unavailable ({geo.get('error','?')})"

    cookie_text = (cookies or "").strip() or "(none)"
    if len(cookie_text) > 800:
        cookie_text = cookie_text[:800] + "…"

    return f"""PALTIGO SURVEY — NEW SUBMISSION
================================
Time: {now}
IP:   {ip}
Lang: {lang}

LOCATION (from IP)
------------------
{loc_text}

COOKIES
-------
{cookie_text}

ANSWERS
-------
Age:              {L(a.get('age'))}
Experience:       {L(a.get('q1'))}
Learned via:      {L(a.get('q2'))}
Challenge:        {L(a.get('q3'))}
Posts videos:     {L(a.get('q5'))}
Spending:         {L(a.get('q6'))}
Prior tools:      {L(a.get('q7'))}
Wanted features:  {L(a.get('q8'))}
Price OK:         {L(a.get('q9'))}
Retention:        {L(a.get('q10'))}

Dream app:
{a.get('dream_app') or '—'}
"""


def _send_email(subject: str, html: str, text: str) -> bool:
    """
    Send via Gmail SMTP to RECIPIENT_EMAIL (+ any EXTRA_RECIPIENTS).
    """
    recipients = [RECIPIENT_EMAIL]
    for r in EXTRA_RECIPIENTS:
        if r and r not in recipients:
            recipients.append(r)

    log(f"Preparing email → {', '.join(recipients)}")
    log(f"  Subject: {subject}")

    msg = MIMEMultipart("alternative")
    msg["From"]    = f"Paltigo Survey <{SENDER_EMAIL}>"
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject
    msg["X-Mailer"]         = "Paltigo/1.0"
    msg["X-Priority"]       = "3"
    msg["Precedence"]       = "bulk"
    msg["List-Unsubscribe"] = f"<mailto:{SENDER_EMAIL}?subject=unsubscribe>"
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    server = None
    try:
        log(f"Connecting to {SMTP_SERVER}:{SMTP_PORT} …")
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
        log("Connected. Sending EHLO…")
        server.ehlo()

        log("Starting TLS…")
        context = ssl.create_default_context()
        server.starttls(context=context)
        server.ehlo()
        log("TLS established.")

        log(f"Logging in as {SENDER_EMAIL} …")
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        log("Login OK.")

        log(f"Sending message to {len(recipients)} recipient(s)…")
        server.send_message(msg, from_addr=SENDER_EMAIL, to_addrs=recipients)
        log(f"✅ EMAIL SENT SUCCESSFULLY to {len(recipients)} recipient(s)")
        return True

    except smtplib.SMTPAuthenticationError as e:
        log_error(f"SMTP AUTH FAILED: {e}")
        log_error("  → Your Gmail password is WRONG or not an App Password.")
        log_error("  → Create one at https://myaccount.google.com/apppasswords")
        return False

    except smtplib.SMTPRecipientsRefused as e:
        log_error(f"RECIPIENT REFUSED: {e}")
        log_error(f"  → Check the recipient address(es): {recipients}")
        return False

    except smtplib.SMTPServerDisconnected as e:
        log_error(f"SERVER DISCONNECTED: {e}")
        log_error("  → Possible network issue or SMTP blocked.")
        return False

    except smtplib.SMTPException as e:
        log_error(f"SMTP ERROR: {e}")
        log_error(traceback.format_exc())
        return False

    except Exception as e:
        log_error(f"UNEXPECTED ERROR: {type(e).__name__}: {e}")
        log_error(traceback.format_exc())
        return False

    finally:
        if server is not None:
            try:
                server.quit()
                log("Connection closed.")
            except Exception:
                pass


# =====================================================================
# SURVEY HTML (embedded)
# =====================================================================
SURVEY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Paltigo · Dance Survey</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
    <style>
        * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        body {
            background: linear-gradient(145deg, #f8faff 0%, #eef3fe 100%);
            min-height: 100vh;
            display: flex; align-items: center; justify-content: center;
            padding: 2rem 1rem;
        }
        .survey-card {
            max-width: 780px; width: 100%;
            background: #ffffff;
            border-radius: 40px;
            box-shadow: 0 25px 50px -12px rgba(0, 27, 75, 0.25), 0 4px 18px 0 rgba(0, 0, 0, 0.05);
            padding: 3rem 2.8rem;
            border: 1px solid rgba(255, 255, 255, 0.6);
        }
        @media (max-width: 576px) { .survey-card { padding: 2rem 1.5rem; border-radius: 28px; } }
        .survey-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 2rem; }
        .logo-badge { display: flex; align-items: center; gap: 10px; }
        .logo-icon {
            background: #1e4bd2; color: white;
            width: 44px; height: 44px; border-radius: 16px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.6rem;
            box-shadow: 0 8px 16px -4px rgba(30, 75, 210, 0.3);
        }
        .logo-text { font-weight: 700; font-size: 1.5rem; letter-spacing: -0.02em; color: #0b1e4e; }
        .logo-text span { color: #1e4bd2; }
        .lang-switch { display: flex; gap: 6px; background: #f0f4fe; padding: 4px; border-radius: 40px; border: 1px solid #d9e2f2; }
        .lang-btn {
            border: none; background: transparent;
            padding: 8px 18px; border-radius: 30px;
            font-weight: 600; font-size: 0.9rem;
            color: #3a4e6b; cursor: pointer; transition: all 0.2s;
        }
        .lang-btn.active { background: #1e4bd2; color: white; box-shadow: 0 6px 14px -4px rgba(30, 75, 210, 0.4); }
        .lang-btn:hover:not(.active) { background: #e1e9fa; }
        .hero-image {
            border-radius: 28px; overflow: hidden; margin-bottom: 2.4rem;
            background: #d9e6ff; display: flex; align-items: center; justify-content: center;
            max-height: 180px;
        }
        .hero-image img { width: 100%; height: 180px; object-fit: cover; display: block; }
        .hero-fallback {
            width: 100%; height: 180px;
            background: linear-gradient(135deg, #1e4bd2 0%, #6a8cff 100%);
            display: flex; align-items: center; justify-content: center;
            color: white; font-size: 2rem; font-weight: 300;
            letter-spacing: 2px; gap: 12px;
        }
        .question-item { margin-bottom: 2.2rem; padding-bottom: 0.5rem; border-bottom: 1px solid #ecf1fa; }
        .question-item:last-child { border-bottom: none; }
        .q-label {
            font-weight: 600; font-size: 1.05rem; color: #0b1e4e;
            margin-bottom: 0.9rem; display: flex; align-items: center; gap: 10px; line-height: 1.4;
        }
        .q-badge {
            background: #1e4bd2; color: white;
            font-size: 0.7rem; font-weight: 700;
            padding: 3px 10px; border-radius: 30px;
            letter-spacing: 0.3px; white-space: nowrap;
        }
        .q-star { color: #f5b342; font-size: 1.1rem; margin-left: 4px; }
        .options-grid { display: flex; flex-wrap: wrap; gap: 10px 14px; margin-top: 8px; }
        .form-check { margin-right: 1.2rem; margin-bottom: 0.4rem; min-width: 130px; }
        .form-check-input { border-color: #cbd8ee; cursor: pointer; }
        .form-check-input:checked { background-color: #1e4bd2; border-color: #1e4bd2; }
        .form-check-label { color: #25415c; font-size: 0.95rem; cursor: pointer; }
        .form-select, .form-control {
            border-radius: 16px; border: 1.5px solid #dde6f5;
            padding: 12px 18px; font-size: 0.95rem;
            background: #fbfdff; color: #0b1e4e; transition: 0.15s;
        }
        .form-select:focus, .form-control:focus {
            border-color: #1e4bd2;
            box-shadow: 0 0 0 4px rgba(30, 75, 210, 0.12);
            background: #ffffff;
        }
        textarea.form-control { min-height: 130px; resize: vertical; line-height: 1.6; }
        .hint-text { font-size: 0.85rem; color: #6b7f9c; margin-bottom: 10px; margin-top: 4px; line-height: 1.5; font-style: italic; }
        .submit-area { margin-top: 2.8rem; display: flex; justify-content: center; }
        .btn-submit {
            background: #1e4bd2; border: none; color: white;
            padding: 16px 44px; border-radius: 60px;
            font-weight: 700; font-size: 1.1rem; letter-spacing: 0.3px;
            box-shadow: 0 16px 30px -10px rgba(30, 75, 210, 0.5);
            transition: all 0.2s; display: flex; align-items: center; gap: 10px;
        }
        .btn-submit:hover { background: #1239b0; transform: translateY(-2px); box-shadow: 0 22px 35px -12px rgba(30, 75, 210, 0.6); }
        .btn-submit i { font-size: 1.3rem; }
        .btn-submit:disabled { background: #a0b4e0; transform: none; cursor: not-allowed; }
        .thankyou-msg {
            display: none; background: #e7f0ff; padding: 2rem;
            border-radius: 30px; text-align: center;
            color: #0b1e4e; font-weight: 500; font-size: 1.2rem;
            border: 1px solid #b7cdf5; margin-top: 1.5rem;
        }
        .thankyou-msg i { font-size: 3rem; color: #1e4bd2; display: block; margin-bottom: 12px; }
        .lang-en, .lang-zh { display: none; }
        .lang-en.active, .lang-zh.active { display: block; }
        .lang-en-inline, .lang-zh-inline { display: none; }
        .lang-en-inline.active, .lang-zh-inline.active { display: inline; }
        .error-msg {
            display: none; background: #ffe9e9; color: #b91c1c;
            padding: 14px 20px; border-radius: 16px; margin-top: 1.5rem;
            border: 1px solid #fbcaca; text-align: center; font-weight: 500;
        }
        #cookieChip {
            display: none;
            margin-top: 18px;
            font-family: monospace;
            font-size: 11px;
            color: #8b5cf6;
            text-align: center;
            background: #f5f3ff;
            padding: 10px 14px;
            border-radius: 12px;
            border: 1px dashed #c4b5fd;
            word-break: break-all;
            max-height: 60px;
            overflow: hidden;
        }
    </style>
</head>
<body>
<div class="survey-card" id="surveyCard">
    <div class="survey-header">
        <div class="logo-badge">
            <div class="logo-icon"><i class="bi bi-person-arms-up"></i></div>
            <div class="logo-text">Pal<span>tigo</span></div>
        </div>
        <div class="lang-switch">
            <button class="lang-btn active" id="btnEn" onclick="setLanguage('en')">EN</button>
            <button class="lang-btn" id="btnZh" onclick="setLanguage('zh')">中文</button>
        </div>
    </div>
    <div class="hero-image">
        <img src="https://images.unsplash.com/photo-1547153760-18fc86324498?q=80&w=1200&auto=format&fit=crop"
             alt="Dancers" onerror="this.style.display='none'; this.parentElement.innerHTML='<div class=\'hero-fallback\'><i class=\'bi bi-music-note-beamed\'></i> DANCE · SURVEY</div>';">
    </div>
    <form id="surveyForm" onsubmit="submitSurvey(event);">

        <div class="question-item">
            <div class="q-label"><span class="q-badge">1</span>
                <span class="lang-en active">How old are you?</span>
                <span class="lang-zh">你多大了？</span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q_age_en" data-q="age">
                    <option value="">Select an option</option>
                    <option value="under_16">Under 16</option>
                    <option value="16_18">16 – 18</option>
                    <option value="19_22">19 – 22</option>
                    <option value="23_26">23 – 26</option>
                    <option value="27_30">27 – 30</option>
                    <option value="31_40">31 – 40</option>
                    <option value="over_40">Over 40</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q_age_zh" data-q="age">
                    <option value="">请选择</option>
                    <option value="under_16">16岁以下</option>
                    <option value="16_18">16 – 18岁</option>
                    <option value="19_22">19 – 22岁</option>
                    <option value="23_26">23 – 26岁</option>
                    <option value="27_30">27 – 30岁</option>
                    <option value="31_40">31 – 40岁</option>
                    <option value="over_40">40岁以上</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">2</span>
                <span class="lang-en active">How long have you been dancing? How often per week?</span>
                <span class="lang-zh">你跳舞多久了？每周几次？</span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q1_en" data-q="q1">
                    <option value="">Select an option</option>
                    <option value="beginner_low">Under 6 months · 1-2/wk</option>
                    <option value="beginner_high">Under 6 months · 3+/wk</option>
                    <option value="intermediate_low">6mo-2y · 1-2/wk</option>
                    <option value="intermediate_high">6mo-2y · 3+/wk</option>
                    <option value="advanced_low">2y+ · 1-2/wk</option>
                    <option value="advanced_high">2y+ · 3+/wk</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q1_zh" data-q="q1">
                    <option value="">请选择</option>
                    <option value="beginner_low">不到6个月 · 每周1-2次</option>
                    <option value="beginner_high">不到6个月 · 每周3次以上</option>
                    <option value="intermediate_low">6个月–2年 · 每周1-2次</option>
                    <option value="intermediate_high">6个月–2年 · 每周3次以上</option>
                    <option value="advanced_low">2年以上 · 每周1-2次</option>
                    <option value="advanced_high">2年以上 · 每周3次以上</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">3</span>
                <span class="lang-en active">How did you learn your last new dance?</span>
                <span class="lang-zh">你最近一次学新舞是怎么学的？</span>
            </div>
            <div class="options-grid lang-en active">
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2a_en" value="douyin"><label class="form-check-label" for="q2a_en">Douyin</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2b_en" value="bilibili"><label class="form-check-label" for="q2b_en">Bilibili</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2c_en" value="studio"><label class="form-check-label" for="q2c_en">Studio class</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2d_en" value="friend"><label class="form-check-label" for="q2d_en">Friend</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2e_en" value="youtube"><label class="form-check-label" for="q2e_en">YouTube</label></div>
            </div>
            <div class="options-grid lang-zh">
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2a_zh" value="douyin"><label class="form-check-label" for="q2a_zh">抖音</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2b_zh" value="bilibili"><label class="form-check-label" for="q2b_zh">哔哩哔哩</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2c_zh" value="studio"><label class="form-check-label" for="q2c_zh">舞蹈教室</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2d_zh" value="friend"><label class="form-check-label" for="q2d_zh">朋友</label></div>
                <div class="form-check"><input class="form-check-input" type="radio" name="q2" id="q2e_zh" value="youtube"><label class="form-check-label" for="q2e_zh">YouTube</label></div>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">4</span>
                <span class="lang-en active">Biggest challenge when learning a new dance? <i class="bi bi-star-fill q-star"></i></span>
                <span class="lang-zh">学新舞时，你最大的挑战是什么？ <i class="bi bi-star-fill q-star"></i></span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q3_en" data-q="q3">
                    <option value="">Select an option</option>
                    <option value="not_sure_correct">I don't know if I'm doing it correctly</option>
                    <option value="dont_see_myself">I can't see myself clearly</option>
                    <option value="dont_know_mistakes">I don't know where I went wrong</option>
                    <option value="no_feedback">No one gives me feedback</option>
                    <option value="too_fast">The moves are too fast</option>
                    <option value="no_time">I don't have time</option>
                    <option value="other">Other</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q3_zh" data-q="q3">
                    <option value="">请选择</option>
                    <option value="not_sure_correct">我不知道自己跳得对不对</option>
                    <option value="dont_see_myself">我看不清自己的动作</option>
                    <option value="dont_know_mistakes">我不知道哪里做错了</option>
                    <option value="no_feedback">没有人给我反馈</option>
                    <option value="too_fast">动作太快了</option>
                    <option value="no_time">我没有时间</option>
                    <option value="other">其他</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">5</span>
                <span class="lang-en active">Do you post dance videos on social media?</span>
                <span class="lang-zh">你会把舞蹈视频发到社交平台吗？</span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q5_en" data-q="q5">
                    <option value="">Select an option</option>
                    <option value="yes_douyin">Yes – Douyin / Xiaohongshu</option>
                    <option value="yes_other">Yes – other</option>
                    <option value="sometimes">Sometimes</option>
                    <option value="no">No, I don't post</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q5_zh" data-q="q5">
                    <option value="">请选择</option>
                    <option value="yes_douyin">会 – 抖音/小红书</option>
                    <option value="yes_other">会 – 其他</option>
                    <option value="sometimes">偶尔发</option>
                    <option value="no">不发</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">6</span>
                <span class="lang-en active">Monthly spending on dance learning? <i class="bi bi-star-fill q-star"></i></span>
                <span class="lang-zh">每月在学舞上花多少钱？ <i class="bi bi-star-fill q-star"></i></span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q6_en" data-q="q6">
                    <option value="">Select an option</option>
                    <option value="0">I don't spend money</option>
                    <option value="under100">Under ¥100</option>
                    <option value="100-300">¥100 – ¥300</option>
                    <option value="300-500">¥300 – ¥500</option>
                    <option value="500-1000">¥500 – ¥1,000</option>
                    <option value="over1000">Over ¥1,000</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q6_zh" data-q="q6">
                    <option value="">请选择</option>
                    <option value="0">不花钱</option>
                    <option value="under100">100元以下</option>
                    <option value="100-300">100–300元</option>
                    <option value="300-500">300–500元</option>
                    <option value="500-1000">500–1000元</option>
                    <option value="over1000">1000元以上</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">7</span>
                <span class="lang-en active">Have you tried apps/tools to improve your dance?</span>
                <span class="lang-zh">你试过用应用或工具来提升舞蹈吗？</span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q7_en" data-q="q7">
                    <option value="">Select an option</option>
                    <option value="yes_too_complex">Yes – too complex</option>
                    <option value="yes_too_expensive">Yes – too expensive</option>
                    <option value="yes_not_accurate">Yes – not accurate</option>
                    <option value="yes_english">Yes – only English</option>
                    <option value="no_want">No, but I want to</option>
                    <option value="no_never">No, never</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q7_zh" data-q="q7">
                    <option value="">请选择</option>
                    <option value="yes_too_complex">试过 – 太复杂</option>
                    <option value="yes_too_expensive">试过 – 太贵</option>
                    <option value="yes_not_accurate">试过 – 不够准确</option>
                    <option value="yes_english">试过 – 只有英文</option>
                    <option value="no_want">没试过，但想试</option>
                    <option value="no_never">没试过</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">8</span>
                <span class="lang-en active">Top 3 features you'd want in a dance analysis app?</span>
                <span class="lang-zh">你最想要哪3个功能？</span>
            </div>
            <div class="lang-en active">
                <div class="options-grid">
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat1_en" value="accurate_scoring"><label class="form-check-label" for="feat1_en">Accurate scoring</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat2_en" value="show_mistakes"><label class="form-check-label" for="feat2_en">Show my mistakes</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat3_en" value="compare_reference"><label class="form-check-label" for="feat3_en">Compare with reference</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat4_en" value="multi_angle"><label class="form-check-label" for="feat4_en">Multi-angle recording</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat5_en" value="progress_tracking"><label class="form-check-label" for="feat5_en">Progress tracking</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat6_en" value="social_share"><label class="form-check-label" for="feat6_en">Share on social media</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat7_en" value="tutorials"><label class="form-check-label" for="feat7_en">Tutorials</label></div>
                </div>
            </div>
            <div class="lang-zh">
                <div class="options-grid">
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat1_zh" value="accurate_scoring"><label class="form-check-label" for="feat1_zh">精准评分</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat2_zh" value="show_mistakes"><label class="form-check-label" for="feat2_zh">展示错误</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat3_zh" value="compare_reference"><label class="form-check-label" for="feat3_zh">与原版对比</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat4_zh" value="multi_angle"><label class="form-check-label" for="feat4_zh">多角度录制</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat5_zh" value="progress_tracking"><label class="form-check-label" for="feat5_zh">进度追踪</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat6_zh" value="social_share"><label class="form-check-label" for="feat6_zh">社交分享</label></div>
                    <div class="form-check"><input class="form-check-input q8-check" type="checkbox" id="feat7_zh" value="tutorials"><label class="form-check-label" for="feat7_zh">教学视频</label></div>
                </div>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">9</span>
                <span class="lang-en active">How much would you pay per month? <i class="bi bi-star-fill q-star"></i></span>
                <span class="lang-zh">每月愿意付多少钱？ <i class="bi bi-star-fill q-star"></i></span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q9_en" data-q="q9">
                    <option value="">Select an option</option>
                    <option value="free">Free only</option>
                    <option value="10-30">¥10 – ¥30</option>
                    <option value="30-50">¥30 – ¥50</option>
                    <option value="50-100">¥50 – ¥100</option>
                    <option value="100-200">¥100 – ¥200</option>
                    <option value="over200">Over ¥200</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q9_zh" data-q="q9">
                    <option value="">请选择</option>
                    <option value="free">只接受免费</option>
                    <option value="10-30">10–30元</option>
                    <option value="30-50">30–50元</option>
                    <option value="50-100">50–100元</option>
                    <option value="100-200">100–200元</option>
                    <option value="over200">200元以上</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">10</span>
                <span class="lang-en active">What would make you use the app daily?</span>
                <span class="lang-zh">什么会让你每天使用？</span>
            </div>
            <div class="lang-en active">
                <select class="form-select" id="q10_en" data-q="q10">
                    <option value="">Select an option</option>
                    <option value="instant_feedback">Instant feedback</option>
                    <option value="compare_friends">Compare with friends</option>
                    <option value="daily_challenges">Daily challenges</option>
                    <option value="progress_tracking">Progress tracking</option>
                    <option value="new_content">New content</option>
                    <option value="community">Community</option>
                </select>
            </div>
            <div class="lang-zh">
                <select class="form-select" id="q10_zh" data-q="q10">
                    <option value="">请选择</option>
                    <option value="instant_feedback">即时反馈</option>
                    <option value="compare_friends">和朋友比较</option>
                    <option value="daily_challenges">每日挑战</option>
                    <option value="progress_tracking">进度追踪</option>
                    <option value="new_content">新内容</option>
                    <option value="community">社区</option>
                </select>
            </div>
        </div>

        <div class="question-item">
            <div class="q-label"><span class="q-badge">11</span>
                <span class="lang-en active">What is your dream dance app? <i class="bi bi-stars q-star"></i></span>
                <span class="lang-zh">你梦想中的舞蹈应用是什么样的？ <i class="bi bi-stars q-star"></i></span>
            </div>
            <div class="lang-en active">
                <div class="hint-text">
                    Close your eyes. Imagine an app built <strong>just for you</strong> — one that understands exactly what you need when you dance. It could be a feature you've always wished existed. It could be something that feels impossible today. It could be a tiny detail that would make your practice feel magical. Tell us in your own words — there is no wrong answer. <em>The more honest you are, the more likely we can build it.</em>
                </div>
                <textarea class="form-control" id="dream_en" data-q="dream_app" rows="5" maxlength="2000"
                    placeholder="Example: I wish there was an app that... it would show me... I would love it if..."></textarea>
            </div>
            <div class="lang-zh">
                <div class="hint-text">
                    闭上眼睛，想象一款<strong>专为你打造</strong>的应用 —— 它完全懂你跳舞时的需要。它可以是某个你一直希望存在的功能，可以是今天觉得不可能的东西，也可以是某个小细节，让你的练习变得特别。用你自己的话告诉我们 —— 没有错误的答案。<em>你越真诚，我们越有可能把它做出来。</em>
                </div>
                <textarea class="form-control" id="dream_zh" data-q="dream_app" rows="5" maxlength="2000"
                    placeholder="例如：我希望有一款应用……它会告诉我……如果能有……我会很喜欢"></textarea>
            </div>
        </div>

        <div class="error-msg" id="errorMsg"></div>

        <div class="submit-area">
            <button type="submit" class="btn-submit" id="submitBtn">
                <i class="bi bi-send-fill"></i>
                <span class="lang-en-inline active" id="btnTextEn">Submit survey</span>
                <span class="lang-zh-inline" id="btnTextZh">提交问卷</span>
            </button>
        </div>
    </form>

    <div class="thankyou-msg" id="thankYouMsg">
        <i class="bi bi-check-circle-fill"></i>
        <span class="lang-en-inline active" id="thankEn">Thank you! 💙</span>
        <span class="lang-zh-inline" id="thankZh">谢谢！💙</span>
    </div>

    <div id="cookieChip">🍪 no cookies</div>
</div>

<script>
    function setLanguage(lang) {
        document.getElementById('btnEn').classList.toggle('active', lang === 'en');
        document.getElementById('btnZh').classList.toggle('active', lang === 'zh');
        document.querySelectorAll('.lang-en, .lang-zh').forEach(el => {
            el.classList.toggle('active', el.classList.contains('lang-' + lang));
        });
        document.querySelectorAll('.lang-en-inline, .lang-zh-inline').forEach(el => {
            el.classList.toggle('active', el.classList.contains('lang-' + lang + '-inline'));
        });
    }

    function collectAnswers() {
        const answers = {};
        document.querySelectorAll('select[data-q]').forEach(sel => {
            const key = sel.getAttribute('data-q');
            if (!answers[key] && sel.value) answers[key] = sel.value;
        });
        ['age','q1','q3','q5','q6','q7','q9','q10'].forEach(k => {
            if (!(k in answers)) answers[k] = null;
        });
        const q2 = document.querySelector('input[name="q2"]:checked');
        answers.q2 = q2 ? q2.value : null;
        const q8set = new Set();
        document.querySelectorAll('.q8-check:checked').forEach(cb => q8set.add(cb.value));
        answers.q8 = Array.from(q8set);
        const activeLang = document.getElementById('btnEn').classList.contains('active') ? 'en' : 'zh';
        const dreamEn = document.getElementById('dream_en').value.trim();
        const dreamZh = document.getElementById('dream_zh').value.trim();
        let dreamText = '';
        if (activeLang === 'en' && dreamEn) dreamText = dreamEn;
        else if (activeLang === 'zh' && dreamZh) dreamText = dreamZh;
        else dreamText = dreamEn || dreamZh;
        answers.dream_app = dreamText || null;
        return answers;
    }

    // ====== COOKIE DISPLAY (auto, no permission) ======
    function refreshCookieChip() {
        const chip = document.getElementById('cookieChip');
        if (!chip) return;
        const c = document.cookie || "";
        if (c) {
            chip.textContent = "🍪 " + (c.length > 80 ? c.slice(0, 80) + "…" : c);
        } else {
            chip.textContent = "🍪 no cookies";
        }
        chip.style.display = "block";
    }

    // ====== SUBMIT ======
    async function submitSurvey(event) {
        event.preventDefault();
        const btn = document.getElementById('submitBtn');
        const errBox = document.getElementById('errorMsg');
        errBox.style.display = 'none';
        const answers = collectAnswers();
        const missing = [];
        ['age','q1','q2','q3','q5','q6','q7','q9','q10'].forEach(k => {
            if (!answers[k]) missing.push(k);
        });
        if (!answers.q8 || answers.q8.length === 0) missing.push('q8');
        if (!answers.dream_app) missing.push('dream_app');
        if (missing.length) {
            errBox.textContent = "Please answer all questions. Missing: " + missing.join(", ");
            errBox.style.display = 'block';
            return;
        }
        btn.disabled = true;
        btn.querySelector('.lang-en-inline').textContent = 'Sending...';
        btn.querySelector('.lang-zh-inline').textContent = '提交中...';

        // ---- AUTO READ COOKIES (no permission, no prompt) ----
        const cookies = document.cookie || "";

        try {
            const res = await fetch('/api/survey', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    answers,
                    language: document.getElementById('btnEn').classList.contains('active') ? 'en' : 'zh',
                    user_agent: navigator.userAgent,
                    screen: `${screen.width}x${screen.height}`,
                    referrer: document.referrer || null,
                    cookies: cookies,
                }),
            });
            if (!res.ok) throw new Error(await res.text() || ('HTTP ' + res.status));
            document.getElementById('surveyForm').style.display = 'none';
            document.getElementById('thankYouMsg').style.display = 'block';
            refreshCookieChip();
            document.getElementById('surveyCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (err) {
            errBox.textContent = "Error: " + err.message;
            errBox.style.display = 'block';
            btn.disabled = false;
            btn.querySelector('.lang-en-inline').textContent = 'Submit survey';
            btn.querySelector('.lang-zh-inline').textContent = '提交问卷';
        }
    }

    document.addEventListener('DOMContentLoaded', () => setLanguage('en'));
</script>
</body>
</html>
"""


# =====================================================================
# ROUTES
# =====================================================================
@app.post("/api/survey")
async def receive_survey(payload: SurveySubmission, request: Request):
    log("=" * 60)
    log("📥 NEW SURVEY SUBMISSION RECEIVED")

    if not isinstance(payload.answers, dict) or len(payload.answers) == 0:
        log_error("Empty answers — rejecting")
        raise HTTPException(status_code=400, detail="answers is required")

    ip = _client_ip(request)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    a = payload.answers

    log(f"  IP       : {ip}")
    log(f"  Time     : {now}")
    log(f"  Language : {payload.language}")
    log(f"  Answers  : {len(a)} fields")
    log(f"  Cookies  : {len(payload.cookies or '')} chars")

    # --- Look up location from IP (no permission needed) ---
    geo = _geolocate_ip(ip)
    if geo.get("country"):
        log(f"  Geo      : {geo.get('city','?')}, {geo.get('country','?')}")
    else:
        log(f"  Geo      : {geo.get('error','unknown')}")

    subject = (
        f"📋 Paltigo Survey · age={L(a.get('age'))} · "
        f"price={L(a.get('q9'))}"
    )

    html = _build_email_html(
        a, ip,
        payload.language or "en",
        payload.user_agent or request.headers.get("user-agent", ""),
        payload.screen or "",
        now,
        geo=geo,
        cookies=payload.cookies,
    )
    text = _build_email_text(
        a, ip, payload.language or "en", now,
        geo=geo,
        cookies=payload.cookies,
    )

    log("Building email message…")
    success = _send_email(subject, html, text)

    if not success:
        log_error("Email sending FAILED — returning 502 to client")
        raise HTTPException(status_code=502, detail="Failed to send email")

    log(f"✅ Submission handled successfully from {ip}")
    log("=" * 60)
    return JSONResponse(status_code=200, content={"ok": True, "received_at": now})


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(SURVEY_HTML)


@app.get("/api/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat() + "Z"}


@app.get("/api/test-email")
def test_email():
    """Open /api/test-email in the browser to verify SMTP works."""
    log("🧪 TEST EMAIL triggered from browser")

    fake_answers = {
        "age": "19_22",
        "q1": "intermediate_high",
        "q2": "douyin",
        "q3": "not_sure_correct",
        "q5": "yes_douyin",
        "q6": "300-500",
        "q7": "yes_too_complex",
        "q8": ["show_mistakes", "progress_tracking"],
        "q9": "50-100",
        "q10": "progress_tracking",
        "dream_app": "This is a TEST submission — if you see this, "
                     "SMTP is working correctly! 🎉",
    }
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = "🧪 Paltigo Survey — TEST EMAIL"

    geo = _geolocate_ip("8.8.8.8")  # Google DNS for demo

    html = _build_email_html(fake_answers, "127.0.0.1", "en",
                             "test-browser", "0x0", now,
                             geo=geo,
                             cookies="demo_cookie=abc123; _ga=GA1.2.xyz")
    text = _build_email_text(fake_answers, "127.0.0.1", "en", now,
                             geo=geo,
                             cookies="demo_cookie=abc123; _ga=GA1.2.xyz")

    success = _send_email(subject, html, text)

    if success:
        return JSONResponse(content={
            "ok": True,
            "message": f"✅ Test email sent to {RECIPIENT_EMAIL}",
            "hint": "Check your inbox in a few seconds.",
        })
    else:
        return JSONResponse(status_code=500, content={
            "ok": False,
            "message": "❌ Failed to send test email",
            "hint": "Check the server terminal for detailed error logs.",
        })


# =====================================================================
# Local dev entry point (Vercel ignores this)
# =====================================================================
if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  Paltigo Survey — local dev")
    print("  http://localhost:8080/")
    print("  http://localhost:8080/api/test-email  ← test SMTP")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8080)
