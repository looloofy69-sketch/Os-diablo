# Security Policy

## Scope

This repository contains governance and technical documentation. The primary system under review is the business-management-assistant-ai v0.4.0 release candidate described in the assessment documents. Report application vulnerabilities in the application repository or through a private channel available to the maintainers.

## Reporting

Please do not publish exploitable details, credentials, customer data, or live endpoint URLs in public issues. Share a concise description, affected version or commit, impact, reproduction conditions, and any mitigation through a private maintainer contact channel. Do not include secrets in the report.

## Security principles

- Sandbox mode is for local development and must not be exposed as a production deployment.
- Non-sandbox environments must fail closed if authentication is not configured.
- Hosted model use must be an explicit data-governance decision, not an accidental consequence of environment variables.
- External actions need authorization, approval policy where applicable, traceable execution outcomes, and safe treatment of ambiguous failures.
- Secrets must be stored outside source control and rotated when exposure is suspected.
- Any security claim must be backed by tests, configuration evidence, or a documented verification result.

## Current limitations

The v0.4.0 review is not a penetration test, compliance audit, or live-system assessment. See the threat model and release verification runbook for the current evidence boundary.
