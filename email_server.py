import os
import smtplib
from email.message import EmailMessage
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

#iniatilaise the standalose email server
mcp = FastMCP("Email-Server")

@mcp.tool()
def send_email(recipient: str, subject: str, body: str) -> str:
    """
    Sends a real email to a recipient using secure SMTP routing.
    Use this tool whenever you need to send an email, dispatch a message, 
    or forward notes to a contact.
    """
    sender_email = os.environ.get("EMAIL_SENDER")
    sender_password = os.environ.get("EMAIL_PASSWORD")

    if not sender_email or not sender_password:
        return "Error: Missing EMAIL_SENDER or EMAIL_PASSWORD environment variables."

    try:
        #production email message payload
        msg = EmailMessage()
        msg["From"] = sender_email
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.set_content(body)

    
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return f"Success: Email successfully dispatched to {recipient} via SMTP server."
    except Exception as e:
        # Intercept any network drops or bad credential rejections cleanly
        return f"Network Error: Failed to send email due to: {str(e)}"


if __name__ == "__main__":
    mcp.run()


