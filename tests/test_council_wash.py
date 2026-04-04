"""Deterministic council context wash (v0)."""

from local_ai.council_wash import prepare_council_contexts


def test_prepare_redacts_uuid_and_email():
    raw = (
        "Contact: a@b.co about project id f47ac10b-58cc-4372-a567-0e02b2c3d479 and also user@example.com."
    )
    native, cloud, tr = prepare_council_contexts(raw)
    assert native == raw
    assert tr["wash_applied"] is True
    assert tr["safety_allow_cloud_with_wash"] is True
    assert tr["cloud_payload_source"] == "washed"
    assert "uuid:" in " ".join(tr["transform_summary"])
    assert "email:" in " ".join(tr["transform_summary"])
    assert cloud is not None
    assert "[REDACTED_UUID]" in cloud
    assert "[REDACTED_EMAIL]" in cloud
    assert "NEUTRAL SNAPSHOT" in cloud


def test_prepare_empty_context():
    native, cloud, tr = prepare_council_contexts("")
    assert native == ""
    assert cloud is None
    assert tr["wash_applied"] is False
