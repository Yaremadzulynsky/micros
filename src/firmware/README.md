# Firmware

**Adding a platform? Start with [the seven platform contracts](contracts/README.md).**

- `contracts/include/micros/`: the APIs every platform supplies and capability checks.
- `platforms/<name>/src/`: matching backend implementations, with private helpers in `support/`.
- `platforms/<name>/target_config.h`: support flags and controller resource budgets.
- `platforms/<name>/sdk/`: SDK startup, build files and boot integration.
- `controller/`: one shared application lifecycle, deployment/rollback policy, command parser and status formatter.
- `kernel/`: shared service execution, deadline supervision, IPC, coordination and image validation.

Startup calls `micros_controller_run()`. The controller loads a stored deployment,
asks the runtime to admit and start its services, and owns health confirmation and
fallback. The runtime creates its tasks and supervisor through `platform.h`.
Storage layout, OS calls and device drivers remain inside the selected platform.

Framework APIs live in `controller/include/micros/` and the kernel's component
headers. Application-facing APIs live in [`src/sdk/abi/include/`](../sdk/abi/include/).
They are distinct from the platform implementation checklist.

All current targets use deployment record `MRG2`, version 1. Rebuild application
packages for the new base; earlier compact/banked deployment records are not
accepted. This source migration does not alter any physical device or its data.
