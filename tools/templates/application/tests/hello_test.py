"""Exercise the starter's real C lifecycle with a deterministic host timer stub."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HelloTest(unittest.TestCase):
    def test_timer_output_and_cleanup(self):
        sdk = Path(os.environ['MICROS_SDK'])
        harness = r'''
#include <assert.h>
#include <string.h>
#include "service.c"
static micros_timer_callback_t callback;
static unsigned opened, closed, messages;
static micros_result_t timer_open(micros_context_t *c, uint64_t delay, uint64_t period,
    micros_timer_callback_t cb, void *data, micros_handle_t *handle) {
    (void)c; (void)data;
    assert(delay == 1000000 && period == 1000000);
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
int main(void) {
    micros_api_t api = {.timer_open=timer_open, .timer_close=timer_close, .debug_write=debug_write};
    hello_state_t state = {0};
    micros_service_args_t args = {.api=&api, .arena=&state};
    assert(initialize(&args) == MICROS_OK);
    assert(start(&args) == MICROS_OK && opened == 1 && messages == 0);
    assert(callback(&args, state.timer, NULL) == MICROS_OK && messages == 1);
    assert(step(&args) == MICROS_OK);
    assert(stop(&args) == MICROS_OK && closed == opened);
}
'''
        output = ROOT / 'build/tests'
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as directory:
            source = Path(directory) / 'hello_test.c'
            source.write_text(harness)
            binary = Path(directory) / 'hello_test'
            subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-std=c17',
                '-Wall', '-Wextra', '-Werror', '-UNDEBUG',
                '-I' + str(sdk / 'src/sdk/abi/include'),
                '-I' + str(ROOT / 'services/hello/src'), str(source), '-o', str(binary)],
                check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
