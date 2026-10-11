# Cloudflare console/device split — 2026-09-07

The Raspberry Pi relay now has two HTTPS listeners in one process with a shared
registry. Docker publishes both on loopback only. Firmware and existing enrollment
files were not changed or reflashed during this migration.

| Hostname | Pi origin | Public access |
| --- | --- | --- |
| console.ydzulynsky.com | https://127.0.0.1:8443 | Cloudflare Access email allowlist plus MFA |
| devices.ydzulynsky.com | https://127.0.0.1:8444 | Exact device poll/result routes and device tokens |
| ydzulynsky.com | https://127.0.0.1:8444 | Legacy device URL, same restrictions |

The console Access application covers the full hostname with no path exclusion.
Its single-email policy uses the owner's corrected Apple relay address. Sessions
and MFA verification last six hours. Biometrics and authenticator applications
are allowed MFA methods. The App Launcher uses the same email policy to permit
self-service MFA enrollment. The console tunnel validates the Access JWT against
the application's audience. Origin TLS certificate validation remains enabled.

At the owner's explicit request, the Pi's private console.json has require_token
set to false. The browser therefore relies on Cloudflare Access; direct access to
the private operator listener is trusted. Operator API bearer tokens and device
tokens remain required. The Mac CLI was updated to use the console hostname and
the user's cached cloudflared Access login, separately from its operator token.

## Verification

- 29 server tests passed, including a command/result round trip across separate
  listeners and attempts to bypass device-only routing with operator tokens,
  forged headers, absolute request targets, and disabled console authentication.
- Public console and operator API requests without Access authentication returned
  a 302 redirect to Cloudflare Access.
- Both device hostnames returned 404 for console/operator APIs, including requests
  carrying the real operator token. Unauthenticated device polling returned 401.
- The private operator API returned 401 without its bearer token. The private
  console API returned 200 with authentication_required=false as requested.
- Safari displayed the fleet directly after Access authentication. The CLI listed
  both enrolled boards, and its cached Access token identified the corrected
  owner email and the expected application audience.
- Both boards were offline at the final check. Hardware reconnection after the
  owner's firmware migration has not been verified.

## Firmware handoff

Use https://devices.ydzulynsky.com as the new device server origin. ESPs retain
their per-device authentication; they do not perform Cloudflare browser login.
Their TLS trust must validate Cloudflare's public edge certificate. The Pi's
private origin certificate is a different trust boundary. Existing firmware URLs
were left unchanged; the previous apex hostname remains device-only during migration.

## Operation and rollback materials

See server/README.md for the Compose override and CLI login workflow. The Pi's
~/micros/DEPLOYMENT.md records its actual restart command and private state paths.
A consistent SQLite backup and original deployment files are in the Pi's private
~/micros/backups/access-split-20260907T155213Z directory. The Mac operator profiles
were backed up under .micros/migrations/cloudflare-access-20260907. Restoring the
old unrestricted public operator route would remove the isolation provided here.
