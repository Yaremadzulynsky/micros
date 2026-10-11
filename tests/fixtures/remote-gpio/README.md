# Remote wiring test

This fixture acquires `test_output`, drives it high, and releases it on stop. Use
only an unconnected output-capable pin. It contains no physical pin constants.

On an enrolled graph-format-3 ESP32, create a board definition with the correct
flash size and `test_output` on GPIO25. Deploy with:

```sh
./micros deploy -d wroom --project tests/fixtures/remote-gpio/micros.toml --board /path/to/test-board.toml
./micros status -d wroom --json
```

Verify the live board inventory reports GPIO25 at level 1 and the service has one
granted/open GPIO. Change only the board file to GPIO26 and repeat deployment with
the same service version. Verify GPIO26 at level 1, then reboot remotely and check
again. `./micros rollback -d wroom` must restore GPIO25 at level 1. The base hash
must remain unchanged throughout. Finally, deploy the device's normal application
and board definition to remove the test binding.

This checks GPIO readback through the MCU and management path; it does not measure
electrical timing or external peripherals.
