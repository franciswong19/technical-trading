import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path

# --- PATH SETUP ---
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent

def get_app_password(filename="app_password.txt"):
    """Retrieves Email App Password from Env Var or local file."""
    app_password = os.getenv('EMAIL_APP_PASSWORD_GITHUB')
    if app_password:
        return app_password

    key_path = project_root / "creds" / filename
    try:
        if key_path.exists():
            with open(key_path, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    return None

def get_receiver_emails(filename="email_list.txt"):
    """
    Retrieves recipients. Handles formats like:
    - email1@abc.com, email2@abc.com
    - email1@abc.com\nemail2@abc.com
    - email1@abc.com, \n email2@abc.com
    """
    raw_data = ""

    # 1. Try GitHub Secret
    env_emails = os.getenv('EMAIL_LIST_GITHUB')
    if env_emails:
        raw_data = env_emails
        print("Using recipient list from environment variables.")
    else:
        # 2. Fallback to local file
        file_path = project_root / "creds" / filename
        if file_path.exists():
            try:
                with open(file_path, "r") as f:
                    raw_data = f.read()
                    print(f"Using local list from: {filename}")
            except Exception as e:
                print(f"Error reading email list: {e}")

    if not raw_data:
        return []

    # CLEANING LOGIC: 
    # Replace all newlines with commas, then split by comma
    cleaned_data = raw_data.replace('\n', ',')
    # Split by comma and strip any surrounding whitespace from each email
    email_list = [email.strip() for email in cleaned_data.split(',') if email.strip()]
    
    return email_list

def send_report_email(receiver_list, file_path, subject=None, body=None, sender_email="your_email@gmail.com"):
    """
    Sends email to receiver_list via BCC for privacy.
    """
    app_password = get_app_password()
    if not app_password or not receiver_list:
        print("Error: Missing credentials or recipient list.")
        return False

    # Default Subject/Body Logic
    date_str = datetime.now().strftime('%Y-%m-%d')
    if subject is None:
        subject = f"Test email on {date_str}"
    if body is None:
        body = f"This is a test email sent on {date_str}."

    # Disclaimer
    disclaimer = (
        "\n\n---\n"
        "DISCLAIMER: This report is for informational purposes only and is not financial advice.\n"
        "Investing involves risk. The sender is not liable for actions taken based on this data.\n"
        "Past performance does not guarantee future results. Consult a professional advisor."
    )
    
    full_body = body + disclaimer

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['Subject'] = subject
    
    # PRIVACY: All recipients moved to BCC
    msg['To'] = sender_email 
    msg['Bcc'] = ", ".join(receiver_list)

    msg.attach(MIMEText(full_body, 'plain'))

    # Attachment logic
    filename = os.path.basename(file_path)
    try:
        with open(file_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename= {filename}")
        msg.attach(part)
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            # send_message correctly routes to the BCC list
            server.send_message(msg)
        print(f"Success! Email sent to {len(receiver_list)} recipients via BCC.")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False