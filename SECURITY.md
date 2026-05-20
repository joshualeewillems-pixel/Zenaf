# Security policy

## Scope

Zenaf is designed for **local development and personal workflow use**. It is **not** production-hardened by default (cookie auth, local SQLite, permissive dev CORS, bootstrap accounts).

Do not expose an unmodified dev instance to the public internet without hardening (TLS, strong secrets, auth review, rate limits, etc.).

## Reporting a vulnerability

If you discover a security issue:

1. **Preferred:** Open a [GitHub private security advisory](https://github.com/YOUR_ORG/zenaf/security/advisories/new) on the public repository once it exists (replace `YOUR_ORG/zenaf` with the actual path).
2. **Alternative:** Contact the maintainer privately (add your email in the published repo’s GitHub profile or issue template).

Please do **not** open a public issue with exploit details before a fix is available.

## What to include

- Description and impact
- Steps to reproduce
- Affected version or commit
- Suggested fix (optional)

## Out of scope (expected dev behavior)

- Default bootstrap passwords documented in [api/README.md](api/README.md)
- Missing `ZENAF_SETTINGS_ENCRYPTION_KEY` causing 503 on credential save (by design)
- Local-only operator notification dry-run mode

## Secrets in the repo

Never commit `.env.local`, `.env.notifications`, IMAP/OAuth JSON, Twilio credentials, or API keys. See [`.env.example`](.env.example) and [`.gitignore`](.gitignore).
