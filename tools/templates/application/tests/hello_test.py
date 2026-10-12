"""Test the real heartbeat and generated lifecycle without hardware or wall-clock waits."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from micros_tooling.config.service_generation import generate, definition
from micros_tooling.config.configuration import config_artifacts

ROOT = Path(__file__).resolve().parents[1]


class HelloTest(unittest.TestCase):
    def test_settings_timer_output_and_cleanup(self):
        sdk = Path(os.environ['MICROS_SDK'])
        contract = ROOT / 'services/hello/service.toml'
        schema = definition(contract)[1]['config_schema']
        config = config_artifacts('hello', dict(fields=schema), dict(interval_ms=250))[1]
        harness = r'''
#include <assert.h>
#include <string.h>
#include "service.c"
#include "hello_lifecycle.c"
static micros_timer_callback_t callback;
static unsigned opened, closed, messages;
static uint64_t expected_interval;
static micros_result_t timer_open(micros_context_t *c, uint64_t delay, uint64_t period,
    micros_timer_callback_t cb, void *data, micros_handle_t *handle) {
    (void)c; (void)data;
    assert(delay == expected_interval && period == expected_interval);
    callback = cb; *handle = 1; opened++; return MICROS_OK;
}
static micros_result_t timer_close(micros_context_t *c, micros_handle_t handle) {
    (void)c; assert(handle == 1); closed++; return MICROS_OK;
}
static micros_result_t debug_write(micros_context_t *c, const uint8_t *data, uint32_t size) {
    (void)c; const char expected[] = "Hello world\n";
    assert(size == sizeof(expected)-1 && !memcmp(data, expected, size));
    messages++; return MICROS_OK;
}
static void check(const uint8_t *config, uint32_t size, uint64_t interval) {
    micros_api_t api = {.timer_open=timer_open, .timer_close=timer_close, .debug_write=debug_write};
    hello_context_t context = {0};
    micros_service_args_t args = {.api=&api, .arena=&context, .config_data=config, .config_bytes=size};
    expected_interval = interval;
    const micros_service_descriptor_t *service = micros_service_query();
    assert(service->init(&args) == MICROS_OK);
    assert(service->start(&args) == MICROS_OK && opened == closed + 1);
    unsigned before = messages;
    assert(callback(&args, context.timer_greeting, NULL) == MICROS_OK && messages == before + 1);
    assert(service->step(&args) == MICROS_OK);
    assert(service->stop(&args) == MICROS_OK && closed == opened);
    assert(service->stop(&args) == MICROS_OK && closed == opened);
}
int main(void) {
    const uint8_t configured[] = {CONFIG_BYTES};
    check(NULL, 0, 1000000);
    check(configured, sizeof(configured), 250000);
}
'''.replace('CONFIG_BYTES', ','.join(str(byte) for byte in config))
        output = ROOT / 'build/tests'
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as directory:
            generated = Path(directory) / 'generated'
            generate(contract, generated)
            source = Path(directory) / 'hello_test.c'
            source.write_text(harness)
            binary = Path(directory) / 'hello_test'
            subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-std=c17',
                '-Wall', '-Wextra', '-Werror', '-UNDEBUG',
                '-I' + str(sdk / 'src/sdk/abi/include'), '-I' + str(generated),
                '-I' + str(ROOT / 'services/hello/src'), str(source), '-o', str(binary)],
                check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
