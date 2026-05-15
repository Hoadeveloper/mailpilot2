import json
import os
import smtplib
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

app.secret_key = os.getenv("SECRET_KEY", "replace-this-with-a-strong-secret")
DEFAULT_SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
DEFAULT_SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
DEFAULT_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
DEFAULT_SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
DEFAULT_SENDER_NAME = os.getenv("SENDER_NAME", "")
SETTINGS_FILE = BASE_DIR / "data" / "settings.json"

DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
TEMPLATES_FILE = DATA_DIR / "templates.json"
HISTORY_FILE = DATA_DIR / "sent_history.json"
SCHEDULE_FILE = DATA_DIR / "scheduled_emails.json"

DEFAULT_TEMPLATES = [
    {
        "name": "Welcome Email",
        "subject": "Welcome to my contact list",
        "body": "Hello {{name}},\n\nThank you for connecting with me.\n\nBest regards,\nYour Name"
    },
    {
        "name": "Follow Up",
        "subject": "Following up on our conversation",
        "body": "Hi {{name}},\n\nI wanted to follow up and see if you had any questions.\n\nRegards,\nYour Name"
    },
    {
        "name": "Announcement",
        "subject": "A quick update for you",
        "body": "Hello,\n\nI wanted to share this update with you today.\n\nThanks,\nYour Name"
    }
]


def ensure_directories():
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    if not TEMPLATES_FILE.exists():
        save_json(TEMPLATES_FILE, DEFAULT_TEMPLATES)
    if not HISTORY_FILE.exists():
        save_json(HISTORY_FILE, [])
    if not SCHEDULE_FILE.exists():
        save_json(SCHEDULE_FILE, [])
    if not SETTINGS_FILE.exists():
        save_json(SETTINGS_FILE, {"last_sender_name": ""})


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def parse_recipients(text):
    recipients = []
    normalized = text.replace(";", ",").replace("\n", ",").replace("\r", ",")
    for part in normalized.split(","):
        if part.strip():
            recipients.append(part.strip())
    return recipients


def build_message(sender, sender_name, recipients, cc, bcc, subject, body, attachments):
    message = EmailMessage()
    if sender_name:
        message["From"] = f"{sender_name} <{sender}>"
    else:
        message["From"] = sender
    message["To"] = ", ".join(recipients)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject
    message.set_content(body)

    for upload in attachments:
        if upload and upload.filename:
            data = upload.read()
            message.add_attachment(
                data,
                maintype="application",
                subtype="octet-stream",
                filename=upload.filename,
            )

    return message


def send_smtp_message(host, port, username, password, message):
    with smtplib.SMTP(host, port, timeout=60) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)


def append_history(entry):
    history = load_json(HISTORY_FILE, []) or []
    history.insert(0, entry)
    save_json(HISTORY_FILE, history[:200])


def add_schedule(entry):
    scheduled = load_json(SCHEDULE_FILE, []) or []
    scheduled.append(entry)
    save_json(SCHEDULE_FILE, scheduled)


def schedule_worker():
    while True:
        scheduled = load_json(SCHEDULE_FILE, []) or []
        now = datetime.now()
        remaining = []
        for item in scheduled:
            due = datetime.fromisoformat(item["send_at"])
            if due <= now:
                try:
                    message = build_message(
                        item["sender"],
                        item.get("sender_name", ""),
                        item["recipients"],
                        item["cc"],
                        item["bcc"],
                        item["subject"],
                        item["body"],
                        []
                    )
                    send_smtp_message(
                        item["smtp_host"],
                        item["smtp_port"],
                        item["sender"],
                        item["password"],
                        message,
                    )
                    append_history({
                        "timestamp": datetime.utcnow().isoformat(),
                        "type": "scheduled",
                        "sender": item["sender"],
                        "recipients": item["recipients"],
                        "subject": item["subject"],
                        "status": "sent",
                    })
                except Exception as exc:
                    append_history({
                        "timestamp": datetime.utcnow().isoformat(),
                        "type": "scheduled",
                        "sender": item["sender"],
                        "recipients": item["recipients"],
                        "subject": item["subject"],
                        "status": "failed",
                        "error": str(exc),
                    })
            else:
                remaining.append(item)
        save_json(SCHEDULE_FILE, remaining)
        time.sleep(20)


def start_scheduler():
    thread = threading.Thread(target=schedule_worker, daemon=True)
    thread.start()


@app.route("/", methods=["GET"])
def index():
    ensure_directories()
    templates = load_json(TEMPLATES_FILE, DEFAULT_TEMPLATES) or []
    history = load_json(HISTORY_FILE, []) or []
    scheduled = load_json(SCHEDULE_FILE, []) or []
    settings = load_json(SETTINGS_FILE, {}) or {}
    last_sender_name = settings.get("last_sender_name") or DEFAULT_SENDER_NAME
    return render_template(
        "index.html",
        templates=templates,
        history=history[:5],
        scheduled=scheduled,
        default_sender=DEFAULT_SENDER_EMAIL,
        default_sender_name=last_sender_name,
        default_host=DEFAULT_SMTP_HOST,
        default_port=DEFAULT_SMTP_PORT,
    )


@app.route("/send", methods=["POST"])
def send():
    ensure_directories()
    sender = request.form.get("sender_email", "").strip() or DEFAULT_SENDER_EMAIL
    password = request.form.get("password", "") or DEFAULT_SMTP_PASSWORD
    smtp_host = request.form.get("smtp_host", "").strip() or DEFAULT_SMTP_HOST
    smtp_port = int(request.form.get("smtp_port", "") or DEFAULT_SMTP_PORT)
    recipients = parse_recipients(request.form.get("recipients", ""))
    cc = parse_recipients(request.form.get("cc", ""))
    bcc = parse_recipients(request.form.get("bcc", ""))
    subject = request.form.get("subject", "").strip()
    body = request.form.get("body", "").strip()
    schedule_time = request.form.get("schedule_time", "").strip()
    template_name = request.form.get("template_name", "")
    attachments = request.files.getlist("attachments")
    recipient_data_str = request.form.get("recipient_data", "")

    if not sender or not password or not (recipients or cc or bcc) or not subject or not body:
        flash("Please fill in sender, password, recipients, subject, and body.", "danger")
        return redirect(url_for("index"))

    if schedule_time:
        try:
            send_at = datetime.fromisoformat(schedule_time)
        except ValueError:
            flash("Invalid schedule date/time.", "danger")
            return redirect(url_for("index"))
        entry = {
            "sender": sender,
            "sender_name": request.form.get("sender_name", ""),
            "password": password,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "recipients": recipients,
            "cc": cc,
            "bcc": bcc,
            "subject": subject,
            "body": body,
            "send_at": send_at.isoformat(),
        }
        add_schedule(entry)
        # save last used sender name to settings
        settings = load_json(SETTINGS_FILE, {}) or {}
        settings["last_sender_name"] = entry.get("sender_name", "")
        save_json(SETTINGS_FILE, settings)
        flash(f"Email scheduled for {send_at.strftime('%Y-%m-%d %H:%M')} (local time).", "success")
        return redirect(url_for("index"))

    if template_name:
        flash(f"Using template: {template_name}", "info")

    try:
        sender_name = request.form.get("sender_name", "")
        
        # Check if we have recipient data with names for personalization
        recipient_list_with_names = []
        if recipient_data_str:
            try:
                import json
                recipient_list_with_names = json.loads(recipient_data_str)
            except:
                pass
        
        # If we have personalization data, send individual emails
        if recipient_list_with_names:
            for recipient_obj in recipient_list_with_names:
                recipient_email = recipient_obj.get("email", "").strip()
                recipient_name = recipient_obj.get("name", "").strip()
                
                if not recipient_email:
                    continue
                
                # Personalize subject and body
                personalized_subject = subject.replace("{{name}}", recipient_name)
                personalized_body = body.replace("{{name}}", recipient_name)
                
                # Build message with BCC or CC based on mode
                message = build_message(
                    sender,
                    sender_name,
                    [recipient_email],  # Single recipient
                    cc,
                    bcc,
                    personalized_subject,
                    personalized_body,
                    attachments
                )
                send_smtp_message(smtp_host, smtp_port, sender, password, message)
            
            append_history({
                "timestamp": datetime.utcnow().isoformat(),
                "type": "manual",
                "sender": sender,
                "recipients": [r.get("email") for r in recipient_list_with_names],
                "cc": cc,
                "bcc": bcc,
                "subject": subject,
                "status": "sent",
            })
            flash(f"Emails sent successfully to {len(recipient_list_with_names)} recipients.", "success")
        else:
            # Send single email to all recipients (old behavior)
            message = build_message(sender, sender_name, recipients, cc, bcc, subject, body, attachments)
            send_smtp_message(smtp_host, smtp_port, sender, password, message)
            append_history({
                "timestamp": datetime.utcnow().isoformat(),
                "type": "manual",
                "sender": sender,
                "recipients": recipients,
                "cc": cc,
                "bcc": bcc,
                "subject": subject,
                "status": "sent",
            })
            flash("Email sent successfully.", "success")
        
        # save last used sender name to settings
        settings = load_json(SETTINGS_FILE, {}) or {}
        settings["last_sender_name"] = sender_name
        save_json(SETTINGS_FILE, settings)
    except Exception as exc:
        append_history({
            "timestamp": datetime.utcnow().isoformat(),
            "type": "manual",
            "sender": sender,
            "recipients": recipients,
            "cc": cc,
            "bcc": bcc,
            "subject": subject,
            "status": "failed",
            "error": str(exc),
        })
        flash(f"Failed to send email: {exc}", "danger")

    return redirect(url_for("index"))


@app.route("/template/add", methods=["POST"])
def add_template():
    ensure_directories()
    name = request.form.get("new_template_name", "").strip()
    subject = request.form.get("new_template_subject", "").strip()
    body = request.form.get("new_template_body", "").strip()
    if not name or not subject or not body:
        flash("Template name, subject, and body are required.", "danger")
        return redirect(url_for("index"))
    templates = load_json(TEMPLATES_FILE, DEFAULT_TEMPLATES) or []
    templates.append({"name": name, "subject": subject, "body": body})
    save_json(TEMPLATES_FILE, templates)
    flash(f"Template '{name}' saved.", "success")
    return redirect(url_for("index"))


@app.route("/history")
def history():
    ensure_directories()
    history = load_json(HISTORY_FILE, []) or []
    scheduled = load_json(SCHEDULE_FILE, []) or []
    return render_template("history.html", history=history, scheduled=scheduled)


if __name__ == "__main__":
    ensure_directories()
    start_scheduler()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
