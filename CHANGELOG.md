# Changelog

All notable changes to the OS Diablo governance and documentation repository are recorded here. This log does not represent releases of the separate application repository.

## Unreleased

- Refreshed the v0.4.1 candidate review after stricter model-score evidence validation, typed `outcome_unknown` propagation, outbound URL/route validation, and secret-aware package exclusions.
- Recorded the exact local candidate checksums: source ZIP `8ccf53b1b44f793eeca833c935985c9444c54ae8313fc5af000188a04b29ab18`; bundle `3dbb83ae10b82f80ba9fba0ea694f7b2f0aefa0579f2a466906626f9f1584327`. Binary artifacts remain in the conversation delivery, not this repository.
- Added PERF-01 (Issue #22) to integrate and verify the candidate in a canonical application-source repository and complete blocked release gates.
- Expanded synchronization to 21 backlog tasks and GitHub Issues #2–#22; added finding-to-task and candidate-to-release-gate traceability.
- Added a dependency-free consistency validator and GitHub Actions workflow for backlog-to-issue links, live issue state, and finding traceability.
- Bootstrapped the repository with the v0.4.0 release-candidate assessment, findings register, implementation backlog, architecture baseline, threat model, runbooks, quality matrix, ADR and contribution templates.
