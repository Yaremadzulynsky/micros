# Micros IR console endpoint

`board.console` owns a publisher on the IR command channel and subscribers on
result and waveform channels. Its worker does not consume those subscriber
cursors. The privileged physical or authenticated management transport uses the
endpoint's existing handles through the runtime's host-only console adapter.
The adapter cannot manufacture grants or access stopped/stale instances.
The IR schema bindings belong to this service and the client; the base adapter
handles only channel keys and bounded bytes. This endpoint has no GPIO grants.

The shipped IR graphs place the console endpoint at service index 0:

- `IPC INFO` reports transport version 1.
- `IPC WRITE 0 1 HEX` publishes a protobuf command; `IPC QUEUED 1` is not TX completion.
- `IPC READ 0 2` reads a protobuf transmit result.
- `IPC READ 0 3` reads a protobuf waveform chunk.

The same ASCII request is available through authenticated
`POST /v1/platform-command`, with a JSON `reply` response. Relay operation 18 is
already routed by the server. No firmware-specific IR operation is routed there.
The adapter requires no service ABI change. It uses existing port ownership and
channel bounds under the runtime lock; it is privileged operator access, not an
untrusted service API. Do not let a service worker also read the bridge cursors.
