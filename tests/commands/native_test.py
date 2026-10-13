"""Compile and execute real generated C/protobuf, including lifecycle cleanup."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from micros_tooling.config.configuration import load_project, generate_service_headers
from micros_tooling.config.protobuf import RUNTIME, RUNTIME_SOURCES

class NativeTests(unittest.TestCase):
    def test_generated_dispatcher_with_real_nanopb(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            shutil.copytree(ROOT/'examples/typed-commands',directory,dirs_exist_ok=True,ignore=shutil.ignore_patterns('build'))
            contract=directory/'service.toml'
            contract.write_text(contract.read_text()+'''\n[service.commands.echo]
args = { text = { type="string", max_bytes=4 }, enabled="bool" }
returns = { text = { type="string", max_bytes=4 }, enabled="bool" }
''')
            project=directory/'micros.toml'
            project.write_text(project.read_text().replace('["get_value", "set_value"]','["get_value", "set_value", "echo"]'))
            service=load_project(project)['services'][0]
            generate_service_headers(project)
            generated=Path(service['_contract']['directory'])/'generated'
            spec=service['_commands']
            command=[*shlex.split(os.environ.get('CC','cc')), '-std=c11','-Wall','-Wextra','-Werror','-UNDEBUG',
                     '-DMICROS_SERVICE_TARGET=MICROS_BUILD_TARGET',f'-DCONTRACT_ID={spec["contract_id"]}u',
                     f'-DREQUEST_KEY={spec["request_key"]}',f'-DRESPONSE_KEY={spec["response_key"]}',
                     '-I'+str(ROOT/'src/sdk/abi/include'),'-I'+str(ROOT/'src/sdk/abi/internal'),'-I'+str(RUNTIME),'-I'+str(generated),
                     *service['sources'],str(generated/'counter_ipc.c'),
                     *map(str,generated.glob('*.pb.c')),*map(str,RUNTIME_SOURCES),
                     str(ROOT/'tests/commands/native_test.c'),'-o',str(directory/'test')]
            compiled=subprocess.run(command,capture_output=True,text=True,timeout=60)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            executed=subprocess.run([str(directory/'test')],capture_output=True,text=True,timeout=10)
            self.assertEqual(executed.returncode,0,executed.stdout+executed.stderr)

    def test_hook_lifecycle_dispatches_real_commands(self):
        from micros_tooling.config.service_scaffold import create
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            shutil.copytree(ROOT/'examples/typed-commands',directory,dirs_exist_ok=True,ignore=shutil.ignore_patterns('build'))
            shutil.rmtree(directory/'src')
            contract=directory/'service.toml'
            contract.write_text(contract.read_text().replace('[service.build]', '[service.build]\nlifecycle="hooks"')
                .replace(', "src/commands.c"', '') + '''\n[service.commands.echo]
args = { text = { type="string", max_bytes=4 }, enabled="bool" }
returns = { text = { type="string", max_bytes=4 }, enabled="bool" }
''')
            project=directory/'micros.toml'
            project.write_text(project.read_text().replace('["get_value", "set_value"]','["get_value", "set_value", "echo"]'))
            create(contract)
            state=directory/'src/counter_state.h'
            state.write_text(state.read_text().replace('uint8_t reserved;', 'uint32_t value;'))
            (directory/'src/service.c').write_text('''#include "counter_hooks.h"
#include <string.h>
micros_result_t counter_on_start(counter_context_t *ctx) { (void)ctx; return MICROS_OK; }
micros_result_t counter_on_step(counter_context_t *ctx) { (void)ctx; return MICROS_OK; }
micros_result_t counter_on_stop(counter_context_t *ctx) { (void)ctx; return MICROS_OK; }
micros_result_t counter_handle_get_value(counter_context_t *ctx, uint32_t *out_value) {
    *out_value=ctx->state.value; return MICROS_OK;
}
micros_result_t counter_handle_set_value(counter_context_t *ctx, uint32_t arg_value, uint32_t *out_value) {
    ctx->state.value=arg_value; *out_value=arg_value; return MICROS_OK;
}
micros_result_t counter_handle_echo(counter_context_t *ctx, bool arg_enabled, const char *arg_text,
    bool *out_enabled, char *out_text, uint32_t out_text_capacity) {
    (void)ctx;
    if (arg_enabled) memset(out_text, 'x', out_text_capacity);
    else memcpy(out_text, arg_text, out_text_capacity);
    *out_enabled=arg_enabled; return MICROS_OK;
}
''')
            service=load_project(project)['services'][0]
            self.assertTrue(any(p.endswith('counter_lifecycle.c') for p in service['sources']))
            generate_service_headers(project)
            generated=Path(service['_contract']['directory'])/'generated'
            spec=service['_commands']
            harness=(ROOT/'tests/commands/native_test.c').read_text()
            start=harness.index('/* An additional test-only handler')
            end=harness.index('int main(void)', start)
            harness=harness[:start]+harness[end:]
            (directory/'native.c').write_text(harness)
            command=[*shlex.split(os.environ.get('CC','cc')), '-std=c11','-Wall','-Wextra','-Werror','-UNDEBUG',
                '-DMICROS_SERVICE_TARGET=MICROS_BUILD_TARGET',f'-DCONTRACT_ID={spec["contract_id"]}u',
                f'-DREQUEST_KEY={spec["request_key"]}',f'-DRESPONSE_KEY={spec["response_key"]}',
                '-I'+str(ROOT/'src/sdk/abi/include'),'-I'+str(ROOT/'src/sdk/abi/internal'),'-I'+str(RUNTIME),'-I'+str(generated),
                *service['sources'],str(generated/'counter_ipc.c'),
                *map(str,generated.glob('*.pb.c')),*map(str,RUNTIME_SOURCES),
                str(directory/'native.c'),'-o',str(directory/'native')]
            compiled=subprocess.run(command,capture_output=True,text=True,timeout=60)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            executed=subprocess.run([str(directory/'native')],capture_output=True,text=True,timeout=10)
            self.assertEqual(executed.returncode,0,executed.stdout+executed.stderr)
            # A newly declared command must not silently acquire a no-op implementation.
            before=(directory/'src/service.c').read_bytes()
            contract.write_text(contract.read_text()+'\n[service.commands.reset]\nargs = {}\nreturns = {}\n')
            generate_service_headers(project)
            missing=subprocess.run(command,capture_output=True,text=True,timeout=60)
            self.assertNotEqual(missing.returncode,0)
            self.assertIn('counter_handle_reset',missing.stdout+missing.stderr)
            self.assertEqual(before,(directory/'src/service.c').read_bytes())

if __name__=='__main__':unittest.main()
