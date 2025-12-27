import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path

# --- PATH SETUP ---
# Locates the project root to find the creds folder
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent

def get_app_password():
    """Reads the app password from the creds/app_password file."""
    pass_path = project_root / "creds" / "app_password"
    try:
        with open(pass_path, "r") as f:
            # .strip() removes any accidental newlines or spaces
            return f.read().strip()
    except FileNotFoundError:
        print(f"Error: App password file not found at {pass_path}")
        return None

def send_report_email(receiver_email, file_path, sender_email="your_email@gmail.com"):
    """
    Sends an email with the report attached using password from creds file.
    """
    app_password = get_app_password()
    if not app_password:
        return False

    date_str = datetime.now().strftime('%Y-%m-%d')
    subject = f"ETF trend analysis report {date_str}"
    body = f"This is the attached report on ETF trend analysis on {date_str}."

    # Create the root message and fill in headers
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject

    # Attach the body text
    msg.attach(MIMEText(body, 'plain'))

    # Process the attachment
    filename = os.path.basename(file_path)
    try:
        with open(file_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename= {filename}",
        )
        msg.attach(part)
        
        # Connect to Gmail's SMTP server
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.send_message(msg)
            
        print(f"Email sent successfully to {receiver_email} with {filename}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False