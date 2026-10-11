# ADR 0008 — Feather V2 fixed-slot runtime and board demo

Status: Accepted for M5. Date: 2026-09-05.

Port the shared runtime through a FreeRTOS platform layer. Reserve four 8 KiB IRAM / 4 KiB DRAM image slots and link each independently built image to one exported slot. Keep service arenas and stacks in internal memory and leave PSRAM disabled. Use an independent higher-priority deadline supervisor and reclaim a service only after its worker parks and joins.

Expose logical GPIO0 as the onboard red LED (physical GPIO13) and logical GPIO1 as the user button (physical GPIO38, input-only). Native handles enforce exclusivity; board operations enforce input-only restrictions. The hardware demo publishes button samples through the same bounded protobuf channel used on the host and consumes them in separately deployed logger and LED services.

Service images remain tied to the base ELF's exported addresses. This is a declared v1 fixed-slot constraint rather than a general relocation loader. Changing service code within slot budgets needs no base reflash. The physical developer interface can replace the base; remote firmware updates remain outside the architecture.

M5 uses developmental SPIFFS storage with explicit limits. Interrupted writes, protected known-good retention, and automatic health rollback must be established by M6 before claiming transactional deployment.
