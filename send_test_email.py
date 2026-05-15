from app import build_message, send_smtp_message, DEFAULT_SMTP_HOST, DEFAULT_SMTP_PORT, DEFAULT_SENDER_EMAIL, DEFAULT_SMTP_PASSWORD

# Recipients to BCC for privacy
bcc = [
    "olaiwolah10@gmail.com",
    "olaiwolah11@gmail.com",
    "olaiwolah13@gmail.com",
]

# Compose test message
sender = DEFAULT_SENDER_EMAIL
sender_name = "Test Sender"
subject = "Test email — privacy check"
body = "This is a test email sent to verify that recipients are BCC'd and addresses are private."

# Use an explicit To header so recipients don't see each other's addresses
to_list = [sender]
cc = []
attachments = []

message = build_message(sender, sender_name, to_list, cc, bcc, subject, body, attachments)

# Send via configured SMTP
send_smtp_message(DEFAULT_SMTP_HOST, DEFAULT_SMTP_PORT, sender, DEFAULT_SMTP_PASSWORD, message)
print("Test email sent (Bcc recipients):", ", ".join(bcc))
