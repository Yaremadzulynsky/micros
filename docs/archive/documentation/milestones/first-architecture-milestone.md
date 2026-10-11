# Original Proposed Architecture Milestone

Historical scope from the architecture review. The [roadmap](../ROADMAP.md) is authoritative for sequencing and completion.


**Proposal:** validate a minimal end-to-end service path before expanding the SDK.

- Select one MCU and one desktop BSP.
- Independently compile and load a small native service on the MCU.
- Bind a minimal SDK and verify mutable service state.
- Exchange bounded protobuf messages between two services.
- Demonstrate stream overwrite detection for a slow subscriber.
- Stop and restart a service without leaving callbacks or resource ownership behind.
- Reject an incompatible image and a configuration that exceeds available resources.
- Stage and activate an updated service, with defined recovery from interrupted activation.

This is a validation milestone, not a claim that these behaviors are already implemented. Kernel OTA and distributed IPC remain outside this milestone.

