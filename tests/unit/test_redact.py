from __future__ import annotations

from kagura_code.redact import redact_secrets


def test_redact_secrets_masks_sk_keys():
    out = redact_secrets("the token is sk-abc123def456ghi789 and that's it")
    assert "sk-abc123def456ghi789" not in out
    assert "***REDACTED***" in out


def test_redact_secrets_masks_bearer_tokens():
    out = redact_secrets("Authorization: Bearer xyz123abc456")
    assert "Bearer xyz123abc456" not in out
    assert "***REDACTED***" in out
