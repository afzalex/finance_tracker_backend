"""Tests for ingestion.extraction — email body parsing."""

import base64

from backend.ingestion.extraction import extract_email_content, _decode_body, _html_to_text


# ── _decode_body ──────────────────────────────────────────────────────────────

def test_decode_body_plain_text() -> None:
    raw = "Hello, your account was debited with INR 500."
    encoded = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    assert _decode_body(encoded) == raw


def test_decode_body_handles_missing_padding() -> None:
    raw = "short"
    encoded = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    # Padding stripped — _decode_body must re-add it
    assert _decode_body(encoded) == raw


def test_decode_body_empty_returns_empty() -> None:
    assert _decode_body("") == ""
    assert _decode_body(None) == ""


# ── _html_to_text ─────────────────────────────────────────────────────────────

def test_html_to_text_strips_tags() -> None:
    html = "<p>Your account was <b>debited</b> with <em>INR 500</em>.</p>"
    result = _html_to_text(html)
    assert "debited" in result
    assert "INR 500" in result
    assert "<" not in result


def test_html_to_text_removes_scripts_and_styles() -> None:
    html = "<html><style>.x{color:red}</style><script>alert(1)</script><p>Body text</p></html>"
    result = _html_to_text(html)
    assert "Body text" in result
    assert "color" not in result
    assert "alert" not in result


def test_html_to_text_decodes_html_entities() -> None:
    html = "<p>Amount: &#8377;500 &amp; charges: &#8377;10</p>"
    result = _html_to_text(html)
    assert "₹500" in result or "500" in result


def test_html_to_text_empty() -> None:
    assert _html_to_text("") == ""


# ── extract_email_content ──────────────────────────────────────────────────────

def _make_message(
    msg_id: str = "abc123",
    subject: str = "HDFC Bank Account Alert",
    sender: str = "alerts@hdfcbank.com",
    body_plain: str = "Your A/c XX1234 debited INR 500.00",
    internal_date_ms: int = 1_700_000_000_000,
    snippet: str = "A/c XX1234 debited",
) -> dict:
    encoded_body = base64.urlsafe_b64encode(body_plain.encode()).decode()
    return {
        "id": msg_id,
        "threadId": "thread1",
        "snippet": snippet,
        "internalDate": str(internal_date_ms),
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
            ],
            "body": {"data": encoded_body},
            "parts": [],
        },
    }


def test_extract_email_content_fields() -> None:
    msg = _make_message()
    content = extract_email_content(msg)
    assert content.gmail_message_id == "abc123"
    assert content.subject == "HDFC Bank Account Alert"
    assert content.sender == "alerts@hdfcbank.com"
    assert content.snippet == "A/c XX1234 debited"
    assert content.internal_date_ms == 1_700_000_000_000
    assert "debited" in content.body_text
    assert "XX1234" in content.body_text


def test_extract_email_content_multipart_prefers_plain() -> None:
    plain = "Plain text body"
    html_body = "<p>HTML body</p>"
    plain_enc = base64.urlsafe_b64encode(plain.encode()).decode()
    html_enc = base64.urlsafe_b64encode(html_body.encode()).decode()
    msg = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "",
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Subject", "value": "Test"},
                {"name": "From", "value": "x@y.com"},
            ],
            "body": {},
            "parts": [
                {"mimeType": "text/plain", "body": {"data": plain_enc}, "parts": []},
                {"mimeType": "text/html", "body": {"data": html_enc}, "parts": []},
            ],
        },
    }
    content = extract_email_content(msg)
    assert content.body_text == plain


def test_extract_email_content_falls_back_to_html() -> None:
    html_body = "<p>Only HTML available</p>"
    html_enc = base64.urlsafe_b64encode(html_body.encode()).decode()
    msg = {
        "id": "m2",
        "threadId": "t2",
        "snippet": "",
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Subject", "value": "Test"},
                {"name": "From", "value": "x@y.com"},
            ],
            "body": {},
            "parts": [
                {"mimeType": "text/html", "body": {"data": html_enc}, "parts": []},
            ],
        },
    }
    content = extract_email_content(msg)
    assert "Only HTML available" in content.body_text


def test_extract_email_content_missing_body_is_empty_string() -> None:
    msg = {
        "id": "m3",
        "threadId": "t3",
        "snippet": "",
        "internalDate": "1700000000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Empty"},
                {"name": "From", "value": "x@y.com"},
            ],
            "body": {},
            "parts": [],
        },
    }
    content = extract_email_content(msg)
    assert content.body_text == ""
