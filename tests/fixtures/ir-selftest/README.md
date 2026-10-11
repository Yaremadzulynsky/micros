# Physical IR loopback fixture

This test-only service sends the fixed NEC code `0xbb44ff00` once, then requires
both a successful transmit result and a matching received waveform. It is retained
as source for explicitly configured hardware tests, not as a general diagnostic
package or an automatically executed host test.

A consuming test application must supply the `selftest` command/result/frame
ports and generate `generated/selftest_ipc.h`, configure compatible IR hardware,
and deliberately select the physical stimulus. No standalone recipe is shipped
here. The reference transceiver is in
[`examples/services/ir-capture/`](../../../examples/services/ir-capture/README.md).
