# Security Review Guidance

AirReview guidance:

- Treat hardcoded secrets, API keys, credentials, tokens, and private keys as high severity unless clearly fake test fixtures and safely scoped.
- Look for authorization widening, fail-open checks, missing ownership checks, role bypass, and insecure defaults.
- Review data exposure through logs, telemetry, UI rendering, URLs, error messages, and browser storage.
- Check input handling around SQL, command execution, file paths, redirects, SSRF, template rendering, and unsafe deserialization.
- Prefer focused findings that identify the exact branch change that introduced or aggravated the security risk.
- Do not ask for broad security rewrites when a local guard, validation, or secret-management fix addresses the issue.
- For secret handling, recommend environment variables, managed identity, Key Vault or equivalent managed secret storage.
- For authorization, recommend explicit allow rules and negative tests for disallowed roles or states.

