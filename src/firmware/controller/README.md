# Shared controller

This directory implements framework behavior for every platform. Target authors
implement the [platform contracts](../contracts/README.md), not another controller.

| Framework API | Implementation |
| --- | --- |
| `micros/controller.h` | `controller.c`: startup, commands, durable trials, health confirmation and rollback |
| `micros/application.h` | `application.c`: admission, startup ordering and cooperative shutdown |
| `micros/deployment.h` | Common deployment record; `deployment.c` hashes stored images in bounded chunks |
| `micros/command.h` | Common management operations and bounded request/reply types |
| `micros/status.h`, `micros/network_status.h` | `status.c`, `support/network_status.c`: formatting typed measurements |
| `micros/ipc_console.h` | `protocol/ipc_console.c`: IPC commands |

Platform SDK startup calls `micros_controller_run()`. The controller obtains the
selected graph from `storage.h`, admits every service before running hooks, and
uses the shared runtime for execution. Native reset requests remain whole-device
or whole-process recovery. The POSIX bridge observes this same selection policy.

`protocol/` and `support/` contain private implementation pieces. The controller
contains no SDK headers or target-name branches. Optional behavior is selected
through declared capabilities, not a second controller or deployment format.

Serial/pipes use bounded `RPC` frames. Authenticated HTTP/relay workers submit the
same operations to the controller task. A mutation session owns an expected
selection; an abandoned transfer leaves confirmed images intact. New images and
the deployment record must pass validation before activation, and a trial becomes
confirmed only after the shared health window. Platform storage owns the physical
journal/rename mechanism that makes that selection durable.
