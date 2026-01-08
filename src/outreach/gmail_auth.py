#!/usr/bin/env python3
"""Gmail OAuth authentication and draft creation.

This module handles:
- OAuth 2.0 authentication with Gmail API
- Token storage and refresh (in ~/.config/justin-jobs/)
- Creating email drafts

Setup required:
1. Create Google Cloud project
2. Enable Gmail API
3. Create OAuth 2.0 credentials (Desktop app)
4. Download client_secret.json to ~/.config/justin-jobs/
5. First run will open browser for OAuth consent
"""

import os
import base64
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Config directory outside repo for security
CONFIG_DIR = Path.home() / '.config' / 'justin-jobs'
TOKEN_PATH = CONFIG_DIR / 'token.json'
CREDENTIALS_PATH = CONFIG_DIR / 'client_secret.json'

# Minimal scope - only compose drafts and send
SCOPES = ['https://www.googleapis.com/auth/gmail.compose']


def ensure_config_dir():
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_gmail_service():
    """
    Get authenticated Gmail API service.

    On first run, opens browser for OAuth consent.
    Subsequent runs use stored token (auto-refreshes if expired).

    Returns:
        Gmail API service object

    Raises:
        FileNotFoundError: If client_secret.json not found
        Exception: If authentication fails
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    ensure_config_dir()

    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"OAuth credentials not found at {CREDENTIALS_PATH}\n"
            "Please download client_secret.json from Google Cloud Console\n"
            "and save it to ~/.config/justin-jobs/client_secret.json"
        )

    creds = None

    # Load existing token
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # Refresh or get new credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save token for next run
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)


def create_draft(service, to_addresses, subject, html_body, from_address=None):
    """
    Create a Gmail draft.

    Args:
        service: Gmail API service object
        to_addresses: List of recipient email addresses
        subject: Email subject line
        html_body: HTML email body
        from_address: Sender address (optional, uses account default)

    Returns:
        Dict with draft info including 'id' and web link

    Raises:
        Exception: If draft creation fails
    """
    # Create MIME message
    message = MIMEMultipart('alternative')
    message['to'] = ', '.join(to_addresses)
    message['subject'] = subject

    if from_address:
        message['from'] = from_address

    # Add HTML body
    html_part = MIMEText(html_body, 'html')
    message.attach(html_part)

    # Encode for Gmail API
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

    # Create draft
    draft = service.users().drafts().create(
        userId='me',
        body={'message': {'raw': raw}}
    ).execute()

    # Get draft ID for link
    draft_id = draft['id']
    draft_link = f"https://mail.google.com/mail/u/0/#drafts?compose={draft_id}"

    return {
        'id': draft_id,
        'link': draft_link,
        'message_id': draft.get('message', {}).get('id')
    }


def test_connection():
    """
    Test Gmail API connection.

    Returns:
        True if connection successful, raises exception otherwise
    """
    service = get_gmail_service()
    # Get user's email address to verify connection
    profile = service.users().getProfile(userId='me').execute()
    return profile.get('emailAddress')
