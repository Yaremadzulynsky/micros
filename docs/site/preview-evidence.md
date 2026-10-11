---
hide:
- toc
---

<span class="docs-editorial"></span>

Start here · Release evidence
{: .arch-eyebrow}

# Developer preview: validation and limits

Recorded September 28, 2026. The release freezes the TOML declaration workflow;
the C-declaration prototype and uncommitted named-pin/channel migration are excluded.
The release tag identifies the exact SDK source. `micros-lab` pins its full commit.
{: .arch-intro}

<nav class="docs-section-index" aria-label="On this page"><a href="#actual-feather-v2-demonstration"><span>01</span> Actual Feather V2 demonstration</a><a href="#interruption-and-management-responsiveness"><span>02</span> Interruption and management responsiveness</a><a href="#reproduce-the-demonstration"><span>03</span> Reproduce the demonstration</a><a href="#coverage-boundaries"><span>04</span> Coverage boundaries</a><a href="#host-and-contributor-checks"><span>05</span> Host and contributor checks</a></nav>

## 01 · Actual Feather V2 demonstration {#actual-feather-v2-demonstration}

A remotely connected Adafruit ESP32 Feather V2 (8 MiB) was already provisioned.
No base firmware was flashed, enrollment replaced or credentials copied into Git.
The SDK fetched its exact authenticated base artifacts from the operator's server.

- Base ELF SHA-256: `f171ae7ea6926d4d19f93d5d75b3bb3f00195d41a7df30d2e0a39400e5716cb5`.
- Native ABI: 0 revision 7; graph format 3; selective deployment supported.
- Application behavior: the reference hello timer, with versioned greeting strings.
- Temporary demo: one timer service, 4 KiB worker stack, no service-owned GPIO.

| Step | Observed result |
| --- | --- |
| Deploy `preview.hello` 0.1.0 | Fresh `Micros preview v1` greetings and timer progress |
| Update to 0.1.1 | Fresh `Micros preview v2` greetings; service instance changed; base unchanged |
| Attempt 0.1.2, whose start hook returns `MICROS_ERROR_SERVICE` | Candidate transferred and reached activation; CLI reported `outcome: rolled_back` and the previous application running |
| Inspect recovery | The 0.1.1 graph was selected again, no trial pending, service Running with result 0; the log cursor advanced with additional v2 greetings |
| Restore the original application | Exact archived release restored; four original services Running; a subsequent restoration preview reported action `none` |

Confirmed v1 release: `1e5bdb5102bdf620d86e1c3499958fd5d0813084f46b4c75f3519bf49b2f11db`.
Confirmed v2 release: `99d03b5d0ac1c1f937b5b70f93cb4faf2ab8df6c5f598bc292ba6009dd943b2b`.
Restored original release: `96fef9d24d9a6261218b6cbf26a83ec76fdef9e98321d9cf4a2d9d0753bd58ee`.
The restored release used the other application bank: bank-dependent graph hashes
can differ even when the archived release and all its packages are identical.

## 02 · Interruption and management responsiveness {#interruption-and-management-responsiveness}

An independent observer made **79 successful status requests** during the two
deployments and the failing candidate/recovery interval, with **zero request
failures**. All samples reported connected Wi-Fi, the same resident boot identity
and the same disconnect counter. Request latency was at most **2.435 seconds**.
This establishes responsiveness at the observation cadence, not zero latency or
an uninterrupted guarantee under arbitrary service faults.

The v1→v2 service-instance replacement was bracketed by device status samples
**1.008373 seconds apart**. The failed-start recovery changed the service instance
between samples **0.949261 seconds apart**. No stopped state was captured. The
actual pause was not resolved by this sampling; these intervals are transition
observation windows, **not measured service downtime**. The CLI reported zero
stop-to-confirmation time because this base staged while services were running;
that field must not be advertised as proof of zero interruption.

Download the [sanitized status observations](../assets/preview-evidence/hardware-observations.json).
Raw logs, command receipts, partial attempts and restoration checks remain in the
ignored investigation directory. Initial log reads explicitly reported loss of
older, overwritten history; this demo does not claim a complete historical log.
The website's animation and RAM/flash values remain labeled illustrations.

## 03 · Reproduce the demonstration {#reproduce-the-demonstration}

Follow the [developer-preview journey](developer-preview.md) to run hello, save a
confirmed release, change its greeting and version, deploy, inspect output and
restore the saved release. For a deliberate failure test on a noncritical board,
use a new service version whose `start` hook returns `MICROS_ERROR_SERVICE`.
Preview before deploying, record the confirmed healthy release first, and inspect
status after failure before any retry. Verify `rolled_back`, the expected graph,
fresh output and unchanged base identity. Restore the exact original release.

## 04 · Coverage boundaries {#coverage-boundaries}

- Initial USB flashing and Wi-Fi pairing from blank private state were **not rerun**;
  the owner explicitly deferred that physical acceptance check.
- The live demo used an existing authenticated relay and enrolled board. It does
  not establish a fresh operator's server setup or direct-LAN connection.
- No physical button actuation, LED optical output, sensor calibration, power-loss
  fault injection, cross-board behavior or new base OTA result is claimed.
- Services are trusted native code; failed-start recovery is not memory isolation.

## 05 · Host and contributor checks {#host-and-contributor-checks}

The release includes CI for the complete CTest suite on macOS ARM64 and Linux
x86-64, strict documentation builds, and generation/composition of a new
application with empty operator and device-state directories. The Python setup
selects supported 3.10–3.12 interpreters; ESP-IDF v5.5.2 installation was exercised
from a fresh SDK dependency directory. See the release's CI run for final results.
