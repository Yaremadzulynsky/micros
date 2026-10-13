# Micros IR transceiver service

`board.ir-capture` 2.0.0 owns GPIO27 (demodulating receiver) and GPIO25/A1
(emitter). Both directions run entirely inside the normal service lifecycle.
The service acquires named GPIO grants, subscribes to typed transmit commands,
and publishes typed transmission results and received waveform chunks.
There is no IR-specific command or GPIO/RMT access in the base console.

| Channel | Key | Contract | Direction |
|---|---:|---|---|
| ir.commands | 1 | micros.ir.command v1 | subscribe |
| ir.results | 2 | micros.ir.result v1 | publish |
| ir.frames | 3 | micros.ir.frame v1 | publish |

Commands contain a nonzero request ID and an NEC code, transmitted once at
38 kHz. TX completes asynchronously: each step is bounded, with a 150 ms
completion timeout. Results distinguish sent, busy, invalid, timeout and duplicate
requests. Only the most recently accepted request ID is deduplicated. Transports
must not retry ambiguous sends. Startup drains retained commands; no automatic
transmission occurs at boot. Stop disables output and closes all owned ports/pins.

The ESP32-specific RMT driver uses RX channel 0 with four memory blocks and TX
channel 4 with one block. It must be the sole RMT user in the graph; the current
micros capability model grants GPIO but does not yet arbitrate RMT channels.
APB must remain 80 MHz. Reception retains 1 us envelope durations, up to 256
RMT words / 512 phases, ending after a 20 ms idle gap. An RMT word has two
16-bit halves: bit 15 is the input level, bits 0-14 are duration in microseconds.
Zero duration terminates a capture. Input level 0 normally means an IR mark.
The demodulating receiver does not measure the optical carrier frequency.

Raw frames use 20-word protobuf chunks with sequence, timestamp, total length,
offset and overflow indication. Consumers must detect missing chunks and ring
loss; the eight-message channel is bounded, not a lossless recording stream.
The receiver currently captures arbitrary envelopes; transmission supports NEC.

The consuming application selects this service and a compatible console or command
publisher. The [IR self-test fixture](../../../tests/fixtures/ir-selftest/README.md) can publish a physical test command and
check TX/RX results; select its code and wiring deliberately in that application.
Personal appliance recordings and historical self-test graphs belong to the owning
application, not this SDK. A historical source recipe does not establish the live
selection. Restore a verified retained release after physical tests.

Local driver/lifecycle/transport tests:

```sh
build/python/bin/python tests/services/ir_service_test.py
ctest --test-dir build/host -R 'ir_service|runtime_lifecycle|ipc_boundaries' --output-on-failure
```
