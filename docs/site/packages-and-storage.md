---
title: Packages and compatibility
hide:
  - toc
---

<span class="docs-editorial"></span>

Reference · Packages and compatibility
{: .arch-eyebrow}

# Packages and compatibility

| Artifact | Purpose |
| --- | --- |
| Unit TOML | Mutable source/build input for one device |
| `.mimg` | Native service image |
| `.msp` | Image plus contracts, settings, schemas, and published channel schemas |
| Release bundle | Retained compiled packages and deployment description |
| Base ELF + `sdkconfig` | Exact resident build required for compatible services |

The loader checks calling convention, ABI revision, layout, descriptor, and
resource budgets. A binary built for one controller/base is not a portable binary
for another. Direct ESP32 profiles keep a paired ELF; server-backed builds retrieve
the exact base by its reported hash. A similarly named base is insufficient.

ESP32 service staging reuses two banks. The optional base-OTA layout has two
firmware partitions sharing that same application store. Base rollback does not
restore an application snapshot. See [Deploy and update](deploy-an-application.md)
and [base OTA](update-the-base.md).

Runtime budgets are in [Service API](service-api.md#resources); format ceilings
are in [Declarations](declaration-authoring.md#limits-and-validation). Target slot
limits come from the actual base's exports/admission, not a universal code-size number.

For binary format details, use the [image header](../../src/firmware/kernel/loader/image.h)
and [package validator](../../src/micros_tooling/storage/packages.py). Checksums detect
byte mismatches; they are neither authentication nor native memory isolation.
