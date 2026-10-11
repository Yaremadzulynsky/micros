"""Compile starters and exercise their cleanup without a board."""
from pathlib import Path
import os
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from micros_tooling.config.service_scaffold import create
from micros_tooling.config.service_generation import generate
from micros_tooling.config.protobuf import RUNTIME


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.generated = self.root/'generated'

    def compile(self, sources, *extra):
        result = subprocess.run([
            *shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-Wall', '-Wextra', '-Werror',
            '-I'+str(ROOT/'src/sdk/abi/include'), '-I'+str(ROOT/'src/sdk/abi/internal'),
            '-I'+str(RUNTIME), '-I'+str(self.generated), *map(str, sources), *extra,
        ], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_commands_sources_and_config_compile_and_refuse_overwrites(self):
        text = (ROOT/'examples/typed-commands/service.toml').read_text().replace('"Value"', '{ type = "uint32", min = 0, max = 100 }').replace('[service.build]', '[service.build]\nlifecycle="hooks"')
        text = text.replace('config_schema = {}', 'config_schema = { interval = { type="uint32", default=20, min=1, max=100 } }')
        text = text.replace('"src/commands.c"]', '"src/commands.c", "drivers/output.c"]')
        contract = self.root/'service.toml'
        contract.write_text(text)
        created = create(contract)
        generate(contract, self.generated)
        self.compile([p for p in created if p.suffix == '.c'] + list(self.generated.glob('*_lifecycle.c')), '-fsyntax-only')
        before = {p: p.read_bytes() for p in created}
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            create(contract)
        generate(contract, self.generated)
        self.assertEqual(before, {p: p.read_bytes() for p in created})
        self.assertEqual(contract.read_text(), text)

    def test_subscription_and_publication_starter_compiles(self):
        contract = self.root/'service.toml'
        text = (ROOT/'examples/typed-commands/service.toml').read_text().replace('"Value"', '{ type = "uint32", min = 0, max = 100 }').replace('[service.build]', '[service.build]\nlifecycle="hooks"')
        text = text.replace('subscriptions = {}', '').replace('publications = {}', '')
        (self.root/'sample.proto').write_text('syntax = "proto3"; package example; message Sample { uint32 value = 1; }')
        for kind, name in [('subscriptions', 'input'), ('publications', 'output')]:
            text += f'\n[service.{kind}.{name}]\n' + '''interface="example.sample"
major=1
minor=0
accepts_minor=[0,0]
policy="stream"
depth=4
max_payload=16
schema="sample.proto"
'''
        contract.write_text(text)
        created = create(contract)
        generate(contract, self.generated)
        self.compile([p for p in created if p.suffix == '.c'] + list(self.generated.glob('*_lifecycle.c')), '-fsyntax-only')

    def test_embedded_handlers_when_only_one_source_is_declared(self):
        contract = self.root/'service.toml'
        contract.write_text((ROOT/'examples/typed-commands/service.toml').read_text().replace('"Value"', '{ type = "uint32", min = 0, max = 100 }').replace('[service.build]', '[service.build]\nlifecycle="hooks"').replace(', "src/commands.c"', ''))
        created = create(self.root)
        generate(contract, self.generated)
        self.compile([p for p in created if p.suffix == '.c'] + list(self.generated.glob('*_lifecycle.c')), '-fsyntax-only')
        self.assertNotIn('_Static_assert', (self.root/'src/service.c').read_text())
        self.assertIn('counter_handle_set_value', (self.root/'src/service.c').read_text())

    def test_existing_state_and_symlinks_create_nothing(self):
        contract = self.root/'service.toml'
        text = (ROOT/'examples/typed-commands/service.toml').read_text().replace('"Value"', '{ type = "uint32", min = 0, max = 100 }').replace('[service.build]', '[service.build]\nlifecycle="hooks"')
        contract.write_text(text)
        (self.root/'src').mkdir()
        state = self.root/'src/counter_state.h'
        state.write_text('my state')
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            create(contract)
        self.assertFalse((self.root/'src/service.c').exists())
        self.assertEqual(state.read_text(), 'my state')
        state.unlink()
        (self.root/'src').rmdir()
        with tempfile.TemporaryDirectory() as outside:
            (self.root/'src').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                create(contract)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_changed_command_signature_requires_implementation_update(self):
        contract = self.root/'service.toml'
        text = (ROOT/'examples/typed-commands/service.toml').read_text().replace('"Value"', '{ type = "uint32", min = 0, max = 100 }').replace('[service.build]', '[service.build]\nlifecycle="hooks"')
        contract.write_text(text)
        create(contract)
        before = (self.root/'src/service.c').read_bytes()
        for changed in (
            text.replace('args = { value =', 'args = { persist="bool", value ='),
            text.replace('returns = { value =', 'returns = { extra="bool", value ='),
        ):
            contract.write_text(changed)
            generate(contract, self.generated)
            result = subprocess.run(['cc', '-std=c11', '-fsyntax-only',
                '-I'+str(ROOT/'src/sdk/abi/include'), '-I'+str(ROOT/'src/sdk/abi/internal'),
                '-I'+str(RUNTIME), '-I'+str(self.generated), str(self.root/'src/service.c')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('conflicting types', result.stderr)
            self.assertEqual(before, (self.root/'src/service.c').read_bytes())

    def test_gpio_partial_init_cleanup_and_repeated_stop(self):
        contract = self.root/'service.toml'
        contract.write_text('''[service]
name="example.starter"
version="1.0.0"
capabilities={gpio=["first", "second"], timers=1}
config_schema={}
hardware.first={direction="input"}
hardware.second={direction="output"}
[service.build]
lifecycle="hooks"
api="starter"
sources=["src/service.c"]
descriptor="descriptor"
''')
        create(contract)
        generate(contract, self.generated)
        harness = self.root/'harness.c'
        harness.write_text('''#include <assert.h>
#include "starter_hooks.h"
extern const micros_service_descriptor_t *micros_service_query(void);
static unsigned opened, closed;
static int fail_second = 1;
micros_result_t starter_first_open(const micros_service_args_t *a, micros_handle_t *h) {
    (void)a; ++opened; *h=1; return MICROS_OK;
}
micros_result_t starter_second_open(const micros_service_args_t *a, micros_handle_t *h) {
    (void)a; if (fail_second) return MICROS_ERROR_UNSUPPORTED; ++opened; *h=2; return MICROS_OK;
}
static micros_result_t close_handle(micros_context_t *c, micros_handle_t h) {
    (void)c; assert(h); ++closed; return MICROS_OK;
}
int main(void) {
    starter_context_t state={0};
    micros_api_t api={.gpio_close=close_handle, .timer_close=close_handle};
    micros_service_args_t args={.api=&api, .arena=&state};
    const micros_service_descriptor_t *d=micros_service_query();
    assert(d->init(&args)==MICROS_ERROR_UNSUPPORTED);
    assert(opened==1 && closed==1);
    assert(!d->stop(&args) && closed==1);
    fail_second=0;
    assert(!d->init(&args) && !d->start(&args) && !d->step(&args));
    assert(!d->stop(&args) && opened==3 && closed==3);
    assert(!d->stop(&args) && closed==3);
}
''')
        executable = self.root/'native'
        self.compile([self.root/'src/service.c', self.generated/'starter_lifecycle.c', harness], '-o', str(executable))
        subprocess.run([str(executable)], check=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
