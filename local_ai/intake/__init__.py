"""
Clinic intake workflows: email and fax → classification, PHI detection, optional redaction → structured queue items.
Raw content stays internal; only sanitized text may be sent to external AI (future).
"""
from .classifier import classify
from .redaction import detect_phi, redact
from .email_router import process_email
from .fax_router import process_fax
from .pipeline import run_pipeline, IntakeItem
from .queue_store import add_item, get_queue, get_item, update_item, get_by_external_id
from .bridge import create_task_from_intake_item
from .email_ingestion import (
    poll_ingest_emails,
    get_imap_config_from_env,
    get_imap_config,
    get_imap_config_from_file,
    save_imap_config,
    MailboxConfig,
)

__all__ = [
    "classify",
    "detect_phi",
    "redact",
    "process_email",
    "process_fax",
    "run_pipeline",
    "IntakeItem",
    "add_item",
    "get_queue",
    "get_item",
    "update_item",
    "get_by_external_id",
    "create_task_from_intake_item",
    "poll_ingest_emails",
    "get_imap_config_from_env",
    "get_imap_config",
    "get_imap_config_from_file",
    "save_imap_config",
    "MailboxConfig",
]
