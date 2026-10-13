# Deployment

> Historical architecture discussion and milestone resolutions. The [V1 architecture](../../v1-architecture.md) and [implemented feature matrix](../V1.md) take precedence over original proposals below.

Status: Working architecture. Original direction and review proposals are preserved below. The M0 contract, where present, takes precedence for the initial implementation; other proposals remain unaccepted.

## 14. Service Deployment & Recovery

### V1 Kernel Update Policy

**micros v1 does not support OTA or remote kernel upgrades.**

Remote deployment is restricted to independently deployable **services**. The micros kernel, HAL/BSP, bootloader, and recovery/base image are updated only through a physical development flashing/debug interface such as USB, serial, or JTAG.

The remote management path must not have permission to overwrite the kernel image in v1.

Conceptually:

```text
Remote / Network
    |
    +--> install service
    +--> update service
    +--> remove service
    +--> start/stop/restart service
    +--> logs / diagnostics
    |
    X--> kernel firmware update
```

This intentionally keeps kernel upgrade mechanics outside the initial architecture. Kernel OTA can be introduced later without changing the service package or service lifecycle model.

### Service Deployment

The normal remote update mechanism operates on the service store:

```text
Developer machine
       |
       | network
       v
Management Service
       |
       v
Service Installer
       |
       +--> validate package / ABI / manifest
       +--> validate dependencies and schemas
       +--> write service package to persistent flash
       +--> update installed-service metadata
       +--> load/restart immediately where supported,
            or reboot for deterministic memory relayout
```

### Recovery / Base Image

A separate **minimal base/recovery image** remains desirable, but it is not the normal OTA mechanism.

Its purpose is to provide a known-good recovery environment if the primary micros image becomes unusable. The exact recovery workflow is still TBD and should remain deliberately small and independent from ordinary service deployment.

For v1, the important architectural rule is:

> **Services are remotely deployable. The kernel is physically flashed.**

The exact partition table and recovery behavior remain open design items.


---

### 19.8 Atomic Activation and Recovery

**Open:** service installation transactions and boot failure handling.

A recovery image alone does not define how a partially written service update or newly crashing service is handled.

**Proposal:** separate package staging from activation:

1. Write a candidate package without modifying the active service selection.
2. Validate its integrity, target ABI, manifest, dependencies, and resource requirements.
3. Commit the selected package/configuration atomically using a storage-specific mechanism.
4. Activate immediately only where safe; otherwise reboot into the selected configuration.
5. Retain a previous known-good package/configuration until activation health criteria are satisfied.
6. Fall back after a defined boot-failure threshold without requiring the failing service to run.

The storage mechanism must specify power-loss behavior at every step. Health criteria, retry limits, flash capacity for staging, and persistent-state migration/rollback remain open. Rolling back executable code does not automatically roll back its stored data.


## M4 Local Deployment Resolution

[ADR 0007](decisions/0007-service-packages.md) and [M4](../milestones/M4.md) define implemented package validation, immutable installed storage, deterministic admission, persistent enabled selections, and local lifecycle commands. Interruption-safe activation, health confirmation, and rollback remain M6 work; remote authentication remains M7.

## M7 Remote Management Resolution

[M7](../milestones/M7.md) and the [management contract](../../../../src/firmware/management/README.md) define the implemented base-linked TLS service, physical credential provisioning, request bounds, package authorization and retry behavior. Earlier open authentication and partition wording is superseded by M6/M7.
