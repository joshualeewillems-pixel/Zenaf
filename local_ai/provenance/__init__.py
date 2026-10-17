"""Minting & provenance: fingerprint the file, ledger in a registry.

Spec: ~/workspace/zenaf-minting-provenance-spec.md

Never metadata-in-file (platforms strip it; screenshots destroy it).
Per artifact we store a 64-bit DCT perceptual hash (~8 bytes) + SHA-256,
and keep the ledger (artifacts, derivation DAG, engagement events, reach)
in a SQLite registry. Anything embedded in the file (C2PA, QR) is a hint
that accelerates re-identification, never the record itself.

MVP covers images only. Video/audio/text fingerprinting is phase 2
(the record shape already carries a `modality` field for it).
"""
