# A deployable service with protobuf channels

This example stores an integer in its own arena. It has no GPIO or other physical
outputs. Its `set` subscription accepts a protobuf value from 0 through 100;
`status` publishes the observed value, accepted/rejected command counts, detected
queue loss and a monotonic timestamp. One command is consumed per scheduler step,
and status is emitted after changes and once a second.

The service contract, schemas, source and complete example recipe are included
here. A bridge exposes status through the shared channel stream. This is a raw
protobuf channel example, not a typed shell command contract. The C service independently enforces bounds and handles malformed
messages; host metadata is not its validation boundary.

For a real board, add this service and the two bridge bindings to that board's
application unit, using the example recipe as a reference. Deploy only after
reviewing the resulting application plan: deploying the example recipe directly
replaces the selected board's application. No build or test installs the example.

Once that release is deployed and registered:

```text
feather> ports example.shell
feather> follow example.shell status --seconds 15
```

A queued command and an observed value are separate facts. Check that `accepted`
advances and `value` becomes 42. This example's `set` operation is idempotent in
value, but the shell still never retries writes automatically.

From the SDK root, run the offline host tests with:

```sh
build/python/bin/python -m unittest discover -s tests/terminal -p '*_test.py'
```

These compile the actual example with generated protobuf bindings and test typed
command processing, bounds, malformed data, queue-loss reporting and cleanup.
Typed command HTTP integration tests are separate from this raw-channel example;
no host test establishes hardware operation.
