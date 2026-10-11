# Console Wi-Fi settings — 2026-09-07

Implemented and deployed to the Pi console. Flashed Feather e89f6d30e1a8 over
USB; esptool verified the written hashes. The authenticated relay then reported
the exact prepared base SHA-256:
`941fef99c176b3ae5dce3390abbd169537c858389396b7d081e745f2f185b581`.
The Feather now uses `https://devices.ydzulynsky.com` and its existing device
bearer credential and trusted public CA. TLS validation against that hostname
succeeded; unauthenticated polling returned 401.

Settings offers three ordered primaries and one fallback. A full replacement
is validated before saving; gaps compact without changing relative order.
Existing four-primary USB lists require explicit acknowledgement before replacement.
Blank passwords preserve the matching saved SSID's credential. Passwords are
never returned; write commands bypass SQLite/WAL, and their retained results
are fixed success/error messages. NVS/flash encryption is not enabled by this change.

Validation completed:

- 34 server tests: authentication, same-origin mutations, device-only listener
  isolation, bounds, capability gating, secret-command persistence/timeout/restart.
- 13 USB Wi-Fi tests and one ASan/UBSan controller test covering radio selection,
  fallback, sticky connections, whole-list update validation, gaps, duplicate
  rejection, password preservation, failed storage and secret-free readback.
- Isolated Playwright browser test: three primaries and fallback, save/readback,
  password clearing, duplicate rejection, existing fourth primary acknowledgement,
  older firmware/offline handling, desktop and 390px mobile layout.
- Native ESP-IDF Feather build and USB flash verified successfully.
- Live Cloudflare-protected console GET/POST/GET preserved the existing saved
  network and password. Readback matched; disconnect count remained zero.
- Feather reported `profiles_api: 1`, connected, RSSI -49 dBm, and both existing
  services Running. Local pairing was updated only after authenticated identity
  verification. Existing service deployment and saved Wi-Fi were preserved.
- Public unauthenticated console settings returned a Cloudflare Access 302;
  the device hostname's console settings route returned 404.

The user will enter additional network names/passwords in Settings. Physical
failover across three actual networks and the iPhone hotspot has not been tested;
selection/failure behavior was covered by the deterministic radio test.

The user requested stopping backups during this work. The ongoing full flash
read was interrupted, its incomplete output removed, and no further backups
were made. Existing earlier backups were not modified.
