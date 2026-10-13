# ADR 0003: Experimental C Service Boundary

Status: Selected M0 prototype contract, 2026-09-05. Partially resolves D-004; executable format and relocation remain open.

## Context

M1 needs a concrete interface without prematurely committing to an on-flash image representation or long-term binary compatibility.

## Decision

Use experimental ABI 0 revision 1 with a native descriptor and injected SDK table. Require exact target/revision matching and freestanding service code. The [service contract](../services.md#minimal-abi-profile) specifies ownership and semantics; [service.h](../../../../../src/sdk/abi/include/micros/service.h) owns declarations.

## Alternatives

Direct kernel symbol linkage couples independent services to firmware internals. A stable ABI promise before MCU testing risks locking in an unworkable layout. A runtime such as WASM is outside the established native direction.

## Consequences and Evidence

Host and MCU images differ. Pointer-bearing structs cannot serve as serialized image headers. M0 checks host C/C++ header compatibility; M1 must inspect actual Xtensa output and choose the loader representation. No runtime loader is implemented by this decision.
