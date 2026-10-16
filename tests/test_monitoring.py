"""Automated unit tests for ChangeScope monitoring and SSRF prevention.

All tests are hermetic and mock network interactions to ensure zero external dependencies.
"""

from unittest.mock import MagicMock, patch
import pytest

from backend.monitoring import (
    validate_target_url,
    compute_content_hash,
    extract_clean_text,
    fetch_site_content,
)


def test_validate_target_url_blocks_localhost():
    """Verify SSRF protection blocks direct localhost and loopback IP addresses."""
    blocked_urls = [
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8080/admin",
        "https://127.0.1.1",
    ]
    for url in blocked_urls:
        is_safe, reason = validate_target_url(url)
        assert not is_safe, f"Expected {url} to be blocked, but it passed."
        assert "blocked" in reason.lower() or "prohibited" in reason.lower() or "loopback" in reason.lower()


def test_validate_target_url_blocks_private_networks():
    """Verify SSRF protection blocks RFC 1918 private subnets."""
    private_urls = [
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://192.168.0.254/router",
    ]
    for url in private_urls:
        is_safe, reason = validate_target_url(url)
        assert not is_safe, f"Expected private network {url} to be blocked."
        assert "private" in reason.lower() or "blocked" in reason.lower()


def test_validate_target_url_blocks_cloud_metadata():
    """Verify SSRF protection blocks AWS/GCP/Azure link-local metadata endpoints."""
    metadata_urls = [
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
    ]
    for url in metadata_urls:
        is_safe, reason = validate_target_url(url)
        assert not is_safe, f"Expected cloud metadata {url} to be blocked."


def test_validate_target_url_blocks_invalid_schemes():
    """Verify non-HTTP/HTTPS schemes (e.g. file://, ftp://) are rejected."""
    invalid_schemes = [
        "file:///etc/passwd",
        "ftp://ftp.example.com",
        "gopher://example.com",
        "javascript:alert(1)",
        "",
    ]
    for url in invalid_schemes:
        is_safe, _ = validate_target_url(url)
        assert not is_safe, f"Expected non-HTTP scheme {url} to be blocked."


def test_validate_target_url_accepts_valid_public_domain():
    """Verify that a legitimate public web destination passes SSRF validation."""
    # Mock DNS resolution to return a safe public IP (93.184.216.34) without hitting network
    mock_addrinfo = [(2, 1, 6, "", ("93.184.216.34", 0))]
    with patch("socket.getaddrinfo", return_value=mock_addrinfo):
        is_safe, reason = validate_target_url("https://example.com")
        assert is_safe, f"Expected public URL to be valid, got rejection: {reason}"


def test_compute_content_hash_deterministic():
    """Verify that content hashing is deterministic and case/whitespace sensitive."""
    text1 = "ChangeScope Intelligent Detector"
    text2 = "ChangeScope Intelligent Detector"
    text3 = "ChangeScope Intelligent Detector - Modified"

    hash1 = compute_content_hash(text1)
    hash2 = compute_content_hash(text2)
    hash3 = compute_content_hash(text3)

    assert hash1 == hash2
    assert hash1 != hash3
    assert len(hash1) == 64  # SHA-256 hexadecimal string length


def test_extract_clean_text():
    """Verify HTML cleanup extracts only visible text and strips tags, scripts, and styles."""
    sample_html = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>Sample Page</title>
        <style>body { color: red; }</style>
        <script>console.log("analytics tracking");</script>
      </head>
      <body>
        <header>Header content</header>
        <main>
          <h1>Product Pricing</h1>
          <p>Current price: <strong>$49.99</strong> / month</p>
        </main>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    cleaned = extract_clean_text(sample_html)

    # Should contain main visible text
    assert "Product Pricing" in cleaned
    assert "$49.99 / month" in cleaned

    # Should not contain scripts or style rules
    assert "console.log" not in cleaned
    assert "color: red" not in cleaned


def test_fetch_site_content_with_mock():
    """Verify fetch_site_content correctly handles simulated HTTP responses without internet."""
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = "<html><body><h1>Status OK</h1></body></html>"

    mock_addrinfo = [(2, 1, 6, "", ("93.184.216.34", 0))]

    with patch("socket.getaddrinfo", return_value=mock_addrinfo):
        with patch("requests.Session.get", return_value=mock_response):
            result = fetch_site_content("https://example.com/status")

            assert result["is_success"] is True
            assert result["status_code"] == 200
            assert "Status OK" in result["html"]
            assert result["response_time_ms"] is not None
