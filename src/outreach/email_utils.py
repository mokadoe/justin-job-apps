#!/usr/bin/env python3
"""Email utility functions for outreach.

This module provides:
- Domain extraction from URLs
- Email address candidate generation
- Plain text to HTML conversion
- Email body building with greeting
"""

from urllib.parse import urlparse


def extract_domain(website_url):
    """
    Extract domain from a website URL.

    Examples:
        https://www.openai.com/about -> openai.com
        http://stripe.com/ -> stripe.com
        www.company.io -> company.io
        company.com -> company.com

    Args:
        website_url: URL string (may or may not have protocol)

    Returns:
        Clean domain string, or None if extraction fails
    """
    if not website_url:
        return None

    url = website_url.strip()

    # Add protocol if missing (for urlparse to work)
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]

        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]

        # Remove port if present
        if ':' in domain:
            domain = domain.split(':')[0]

        return domain if domain else None

    except Exception:
        return None


def parse_name(full_name):
    """
    Parse a full name into first and last name, stripping titles and suffixes.

    Handles:
        "Dr Hajra Niaz" -> ("hajra", "niaz")
        "Mr. John Smith Jr." -> ("john", "smith")
        "Jane Doe" -> ("jane", "doe")

    Returns:
        Tuple of (first_name, last_name) in lowercase, or (None, None) if invalid
    """
    if not full_name:
        return None, None

    # Titles to skip at the beginning
    titles = {
        'dr', 'dr.', 'mr', 'mr.', 'mrs', 'mrs.', 'ms', 'ms.',
        'prof', 'prof.', 'professor', 'sir', 'madam', 'rev', 'rev.'
    }

    # Suffixes to skip at the end
    suffixes = {'md', 'pe', 'phd', 'jr', 'jr.', 'sr', 'sr.', 'ii', 'iii', 'iv', 'mba', 'cpa', 'esq', 'esq.'}

    parts = full_name.lower().strip().split()

    # Filter out titles from the beginning
    while parts and (parts[0].rstrip('.') in titles or parts[0] in titles):
        parts.pop(0)

    # Filter out suffixes from the end
    while parts and (parts[-1].rstrip('.') in suffixes or parts[-1] in suffixes):
        parts.pop()

    if not parts:
        return None, None

    first = parts[0]
    last = parts[-1] if len(parts) > 1 else None

    # Remove special characters
    first = ''.join(c for c in first if c.isalnum())
    last = ''.join(c for c in last if c.isalnum()) if last else None

    return first or None, last


def generate_email_candidates(name, domain):
    """
    Generate email address candidates from a contact name and domain.

    Returns 3 candidates ordered by confidence (highest first):
    1. first.last@domain (HIGH)
    2. first@domain (MEDIUM)
    3. flast@domain (MEDIUM)

    Args:
        name: Full name (e.g., "Dr John Smith")
        domain: Company domain (e.g., "openai.com")

    Returns:
        List of dicts with 'email' and 'confidence' keys
    """
    if not name or not domain:
        return []

    first, last = parse_name(name)

    if not first:
        return []

    # Handle single names (no last name)
    if not last:
        return [
            {'email': f"{first}@{domain}", 'confidence': 'medium'}
        ]

    return [
        {'email': f"{first}.{last}@{domain}", 'confidence': 'high'},
        {'email': f"{first}@{domain}", 'confidence': 'medium'},
        {'email': f"{first[0]}{last}@{domain}", 'confidence': 'medium'},
    ]


def generate_generic_emails(domain):
    """
    Generate generic email addresses when no contact is available.

    Args:
        domain: Company domain (e.g., "openai.com")

    Returns:
        List of dicts with 'email' and 'confidence' keys
    """
    if not domain:
        return []

    return [
        {'email': f"jobs@{domain}", 'confidence': 'low'},
        {'email': f"careers@{domain}", 'confidence': 'low'},
        {'email': f"hiring@{domain}", 'confidence': 'low'},
    ]


def text_to_html(message_text):
    """
    Convert plain text message to HTML.

    Handles:
    - Bullet points (lines starting with bullet chars) -> <ul><li>
    - Regular paragraphs -> <p>
    - Preserves line breaks within paragraphs

    Args:
        message_text: Plain text message with bullet points

    Returns:
        HTML string
    """
    if not message_text:
        return ""

    lines = message_text.split('\n')
    html_parts = []
    in_list = False
    current_paragraph = []

    bullet_chars = ('•', '-', '*', '–', '—')

    def flush_paragraph():
        nonlocal current_paragraph
        if current_paragraph:
            text = ' '.join(current_paragraph)
            html_parts.append(f'<p>{text}</p>')
            current_paragraph = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            # Empty line - flush paragraph
            if in_list:
                html_parts.append('</ul>')
                in_list = False
            flush_paragraph()
            continue

        # Check if line is a bullet point
        is_bullet = any(stripped.startswith(char) for char in bullet_chars)

        if is_bullet:
            # Flush any pending paragraph
            flush_paragraph()

            if not in_list:
                html_parts.append('<ul>')
                in_list = True

            # Extract bullet content (remove bullet char and whitespace)
            for char in bullet_chars:
                if stripped.startswith(char):
                    content = stripped[len(char):].strip()
                    break

            html_parts.append(f'<li>{content}</li>')

        else:
            # Regular text
            if in_list:
                html_parts.append('</ul>')
                in_list = False

            current_paragraph.append(stripped)

    # Close any open list
    if in_list:
        html_parts.append('</ul>')

    # Flush remaining paragraph
    flush_paragraph()

    return '\n'.join(html_parts)


def extract_first_name(full_name):
    """
    Extract first name from full name, skipping common titles.

    Handles: "Dr Hajra Niaz" -> "Hajra"
             "Mr. John Smith" -> "John"
             "Jane Doe" -> "Jane"
    """
    if not full_name:
        return None

    # Common titles to skip
    titles = {
        'dr', 'dr.', 'mr', 'mr.', 'mrs', 'mrs.', 'ms', 'ms.',
        'prof', 'prof.', 'professor', 'sir', 'madam', 'rev', 'rev.'
    }

    parts = full_name.strip().split()

    for part in parts:
        # Skip titles
        if part.lower().rstrip('.') in titles or part.lower() in titles:
            continue
        # Return first non-title word
        return part.capitalize()

    # Fallback to first part if all are titles (unlikely)
    return parts[0].capitalize() if parts else None


def build_email_body(message_text, contact_name=None):
    """
    Build complete HTML email body with greeting.

    Args:
        message_text: Plain text message
        contact_name: Contact's full name (optional)

    Returns:
        HTML string with greeting + formatted message
    """
    # Extract first name for greeting
    if contact_name:
        first_name = extract_first_name(contact_name)
        greeting = f"Hi {first_name}," if first_name else "Hi there,"
    else:
        greeting = "Hi there,"

    # Convert message to HTML
    html_body = text_to_html(message_text)

    # Combine greeting + body
    full_html = f'<p>{greeting}</p>\n{html_body}'

    return full_html


def get_email_addresses(contact_name, domain):
    """
    Get email addresses for a contact or generic if no contact.

    Args:
        contact_name: Contact's full name (None for generic)
        domain: Company domain

    Returns:
        List of email strings (no confidence info, just emails)
    """
    if contact_name:
        candidates = generate_email_candidates(contact_name, domain)
    else:
        candidates = generate_generic_emails(domain)

    return [c['email'] for c in candidates]
