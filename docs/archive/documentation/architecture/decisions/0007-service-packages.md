# ADR 0007 — Immutable packages and deterministic local admission

Status: Accepted for M4. Date: 2026-09-05.

Use a deterministic uncompressed ZIP envelope with a strict, bounded member set for independently built service images and schemas. Validate hashes, metadata, and resource declarations before installation. Keep schema content identity separate from explicit interface compatibility versions. The kernel remains application-schema agnostic.

Store immutable content-addressed packages separately from the enabled name/version selection. Plan the entire selected graph before executing any service. Enforce admitted capabilities in the native runtime and compare native descriptor budgets with manifest declarations before starting hooks.

Use a user-private local controller socket and a dedicated native control pipe. Service output goes through a separately bounded diagnostic path. Restart means a fresh image load; local stop does not change next-boot enablement. M4 selection changes require shutdown. Transactional activation and health-based rollback will extend this store in M6.

Consequences: installation can exceed residency, plans are repeatable, and rejected changes leave the selected graph intact. The host still relies on trusted native services and OS loader bookkeeping. Package SHA-256 detects integrity changes but is not signer authorization; authenticated remote management is a separate M7 contract.
