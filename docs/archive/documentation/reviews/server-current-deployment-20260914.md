# Current server deployment — 2026-09-14

Deployed the current checkout's server, web assets and host modules to the existing
tailpi management server. This replaces the older deployment that lacked the
coordination endpoint and coordinator integration. The deployment includes the
`micros_tooling/` package layout and the shared operator capture endpoint.

Preserved the existing `.env`, Compose base, Pi ownership override, tunnel override
and private state mount. Both published listeners remain bound to loopback.
Source hashes were checked against the uploaded manifest. A SQLite online backup
passed `quick_check`; prior source/configuration and private state backups are at
`/home/ydzulynsky/micros/backups/server-current-20260914/`. The former image could
not be tagged by its container-reported digest; rollback would require rebuilding
the retained source with its preserved deployment configuration.

Verification:

- All 74 Python server tests passed, along with five console JavaScript test files.
- The built image passed server import checks before replacing the container.
- Authenticated `GET /v1/coordination` succeeds and reports zero configured routes.
  No routes were created as part of this update.
- Unauthenticated coordination access returns 401 on the operator listener and
  404 on the device-only listener, checked with certificate verification enabled.
- All five device enrollments remain present. Feather and Wroom reconnected with
  their exact base identities and activation records unchanged; their four and
  three application services respectively remain Running with result 0.
- The server's Feather ELF bundle was downloaded and hash-validated against the
  running base. No board firmware or application was deployed.
- A shared Feather pin capture returned 14 samples and one initial device gap,
  preserved in evidence rather than treated as a hardware fault.

Local evidence: `build/server-update-20260914/`, including the source manifest,
test/build/deployment logs, before/after rosters, API verification and pin capture.
This verifies server deployment and connectivity, not the physical IR path or a
cross-board action exchange; those require a separately configured functional test.
