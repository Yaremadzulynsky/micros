# Application tests

Keep tests of your service behavior here. The SDK tests its runtime, ABI and
built-in services; your project owns tests for your own application behavior.

An initial offline configuration check is:

```sh
./micros compose
```

Composition validates declarations and source paths. It does not execute services
or establish that hardware works.

`hello_test.py` compiles the real starter and generated lifecycle and checks default
and selected intervals, greeting and cleanup with a host timer stub. Use
`./micros test -v` for individual results or `./micros test -k NAME` to filter tests.
Update its expected greeting when
editing hello. This does not simulate real MCU timing or physical hardware.
