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

def get_app_password(filename="app_password.txt"):
    """
    Retrieves the Email App Password.
    Checks for a GitHub Secret (environment variable) first.
    Falls back to loading from a text file inside the 'creds' folder.
    """
    # 1. First, try to get the key from the GitHub Secret / Environment Variable
    # Ensure 'EMAIL_APP_PASSWORD_GITHUB' matches the key name in your YML 'env' section
    app_password = os.getenv('EMAIL_APP_PASSWORD_GITHUB')
    
    if app_password:
        print("Using EMAIL_APP_PASSWORD from environment variables.")
        return app_password

    # 2. Fallback: Load from the local text file if not in the cloud
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # '..' moves up to project root, then into 'creds'
    key_path = os.path.join(current_dir, '..', 'creds', filename)

    try:
        if os.path.exists(key_path):
            with open(key_path, "r") as f:
                app_password = f.read().strip()
                if app_password:
                    print(f"Using local app password from: {filename}")
                    return app_password
                else:
                    print(f"Warning: {filename} is empty.")
        else:
            print(f"Error: Local password file '{filename}' not found at {os.path.abspath(key_path)}")
            
    except Exception as e:
        print(f"An error occurred while reading the local password: {e}")
        
    return ""

def send_report_email(receiver_email, file_path, subject=None, body=None, sender_email="your_email@gmail.com"):
    """
    Sends an email with the report attached using password from creds file.
    """
    app_password = get_app_password()
    if not app_password:
        return False

    # Fallback to defaults if no custom parameters are provided
    date_str = datetime.now().strftime('%Y-%m-%d')
    if subject is None:
        subject = f"Test email on {date_str}"
    if body is None:
        body = f"This is a test email sent on {date_str}."

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