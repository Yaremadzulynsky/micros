"""Declarations, native generation, exposure, package metadata and safe scaffolding."""
from pathlib import Path
import shutil
import subprocess
import os
import shlex
import copy
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from micros_tooling.commands import schema, metadata
from micros_tooling.commands.generate import scaffold
from micros_tooling.config.configuration import load_project, generate_service_headers
from micros_tooling.config.protobuf import compile_schema
from micros_tooling.communication.protobuf import message_class
from micros_tooling.storage.packages import canonical_schema, digest


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        shutil.copytree(ROOT/'examples/typed-commands', self.directory, dirs_exist_ok=True,ignore=shutil.ignore_patterns('build'))
        self.project = self.directory/'micros.toml'
        contract = self.directory/'service.toml'
        contract.write_text(contract.read_text().replace('"Value"', '{ type = "uint32", min = 0, max = 100 }'))

    def test_explicit_exposure_generates_bridge_and_validates_packaged_contract(self):
        recipe = load_project(self.project)
        self.assertEqual(len(recipe['services']), 2)
        generate_service_headers(self.project)
        packages = []
        for service in recipe['services']:
            schemas = {k:Path(v).read_bytes() for k,v in service['schemas'].items()}
            contract = metadata.build(service)
            if contract: metadata.validate(contract, service['channels'], schemas)
            manifest = dict(name=service['name'], version=service['version'], channels=service['channels'],
                            schemas={k:digest(canonical_schema(v)) for k,v in schemas.items()})
            if contract: manifest['commands'] = contract
            else: manifest['ipc_bridge'] = True
            packages.append(dict(manifest=manifest))
        bindings = metadata.bind(packages)
        metadata.validate_bindings(bindings)
        self.assertEqual(bindings[0]['service'], 'example.counter')
        self.assertNotEqual(bindings[0]['service_index'], bindings[0]['instance'])
        corrupted = dict(recipe['services'][0]['schemas'])
        corrupted = {k:Path(v).read_bytes().replace(b'fixed64', b'uint64') for k,v in corrupted.items()}
        with self.assertRaisesRegex(ValueError, 'schema differs'):
            metadata.validate(metadata.build(recipe['services'][0]), recipe['services'][0]['channels'], corrupted)
        with self.assertRaisesRegex(ValueError, 'matching bridge'):
            metadata.bind(packages[:1])

    def test_no_exposure_has_no_channels_or_bridge_and_binding_disables_commands(self):
        self.project.write_text(self.project.read_text().replace('expose_commands = ["get_value", "set_value"]', 'expose_commands = []'))
        services = load_project(self.project)['services']
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]['channels'], [])
        generate_service_headers(self.project)
        generated = Path(services[0]['_contract']['directory'])/'generated/counter_commands.c'
        self.assertIn('counter_set_value(', generated.read_text())
        adapter=Path(services[0]['_interface']['directory'])/'generated/counter_bindings.c'
        self.assertIn('default: return false;',adapter.read_text())
        self.assertNotIn('return true;',adapter.read_text())
        self.assertIsNone(metadata.build(services[0]))

    def test_exposure_rejects_unknown_duplicate_and_non_string_values(self):
        original = self.project.read_text()
        for bad in ('["missing"]', '["get_value", "get_value"]', '[["get_value"]]'):
            self.project.write_text(original.replace('["get_value", "set_value"]', bad))
            with self.subTest(bad=bad), self.assertRaises(ValueError): load_project(self.project)

    def test_scaffolding_is_exclusive_and_generated_files_do_not_overwrite_handlers(self):
        output = self.directory/'new_handlers.c'
        scaffold(self.directory/'service.toml', output)
        self.assertIn('counter_set_value_response_t', output.read_text())
        output.write_text('user implementation\n')
        with self.assertRaises(FileExistsError): scaffold(self.directory/'service.toml', output)
        generate_service_headers(self.project)
        self.assertEqual(output.read_text(), 'user implementation\n')

    def test_stale_handlers_fail_compilation_without_overwriting_implementation(self):
        from micros_tooling.config.service_generation import generate
        from micros_tooling.config.protobuf import RUNTIME
        contract = self.directory/'service.toml'
        original = contract.read_text()
        output = self.directory/'handlers.c'
        scaffold(contract, output)
        handwritten = output.read_bytes()
        generated = self.directory/'interfaces'
        def compile_handlers():
            generate(contract, generated)
            self.assertEqual(output.read_bytes(), handwritten)
            return subprocess.run([
                *shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-fsyntax-only',
                '-DMICROS_SERVICE_TARGET=MICROS_BUILD_TARGET',
                '-I'+str(ROOT/'src/sdk/abi/include'), '-I'+str(ROOT/'src/sdk/abi/internal'),
                '-I'+str(RUNTIME), '-I'+str(generated), str(output),
            ], capture_output=True, text=True, timeout=30)
        self.assertEqual(compile_handlers().returncode, 0)
        for replacement in (
            'args = { persist = "bool", value = { type = "uint32", min = 0, max = 100 } }',
            'args = {}',
            'args = { renamed = { type = "uint32", min = 0, max = 100 } }',
            'args = { value = { type = "sint32", min = 0, max = 100 } }',
            'args = { value = { type = "uint32", min = 0, max = 99 } }',
        ):
            with self.subTest(replacement=replacement):
                contract.write_text(original.replace('args = { value = { type = "uint32", min = 0, max = 100 } }', replacement))
                result = compile_handlers()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('command schema changed', result.stderr)
        contract.write_text(original.replace('returns = { value =', 'returns = { extra = "bool", value ='))
        result = compile_handlers()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('command schema changed', result.stderr)
        # A separately scaffolded file provides reviewed literals without touching the old file.
        refreshed = self.directory/'reviewed.c'
        scaffold(contract, refreshed)
        import re
        old_guards = re.findall(r'_Static_assert[^;]+;', output.read_text())
        new_guards = re.findall(r'_Static_assert[^;]+;', refreshed.read_text())
        updated = output.read_text()
        for old, new in zip(old_guards, new_guards):
            updated = updated.replace(old, new)
        output.write_text(updated)
        handwritten = output.read_bytes()
        self.assertEqual(compile_handlers().returncode, 0)
        # Restore the original reviewed literals for a description-only edit.
        for new, old in zip(new_guards, old_guards):
            updated = updated.replace(new, old)
        output.write_text(updated)
        handwritten = output.read_bytes()
        contract.write_text(original.replace('Read the current value', 'Read value'))
        self.assertEqual(compile_handlers().returncode, 0)

    def test_handler_schema_tracks_returns_and_enum_choices_not_description(self):
        from micros_tooling.commands.generate import handler_schema
        original = schema.normalize({'read': dict(returns=dict(color=dict(type='enum', choices=['red', 'blue'])))})['read']
        changed = copy.deepcopy(original)
        changed['returns']['color']['choices'].reverse()
        self.assertNotEqual(handler_schema(original), handler_schema(changed))
        changed = copy.deepcopy(original)
        changed['returns']['extra'] = dict(type='bool')
        self.assertNotEqual(handler_schema(original), handler_schema(changed))
        changed = dict(original, description='Updated prose')
        self.assertEqual(handler_schema(original), handler_schema(changed))

    def test_schema_validation_and_utf8_bounds(self):
        fields = schema.normalize({'echo':dict(args=dict(text=dict(type='string',max_bytes=4), enabled='bool', color='Color', value=dict(type='sint32',min=-2,max=3)))},
                                  {'Color':dict(type='enum',choices=['red','blue'])})['echo']['args']
        parsed = schema.parse_arguments(fields, dict(text='éé',enabled='true',color='blue',value='-2'))
        self.assertEqual(schema.values(fields,parsed), dict(text='éé',enabled=True,color=1,value=-2))
        for key,bad in [('text','ééé'),('text','\0'),('enabled','yes'),('color','green'),('value','4')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                schema.parse_arguments(fields, dict(text='ok',enabled='true',color='red',value='0') | {key:bad})
        for fields in ({'x':'string'}, {'x':dict(type='uint32',min=-1)}, {'x':dict(type='enum',choices=['red','red'])}, {'result':'bool'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):schema.normalize({'test':dict(args=fields)})

    def test_host_and_nanopb_wire_descriptors_agree_and_empty_requests_exist(self):
        commands = schema.normalize({'read':{},'echo':dict(args=dict(text=dict(type='string',max_bytes=12)),returns=dict(ok='bool'))})
        for response in (False,True):
            path=self.directory/('demo_rpc_response.proto' if response else 'demo_rpc_request.proto')
            path.write_text(schema.proto('demo',commands,response))
            compiled=compile_schema(path)
            self.assertLessEqual(compiled['maximum'],schema.MAX_WIRE)
            host=message_class(schema.descriptor('demo',commands,response))
            message=host(request_id=7,contract_id=8)
            message.read.SetInParent()
            decoded=host.FromString(message.SerializeToString())
            self.assertEqual(decoded.WhichOneof('command'),'read')
            self.assertIn('Command_echo', '\n'.join(compiled['files'].values()))

    def test_service_generation_needs_no_board_and_exposure_does_not_change_interfaces(self):
        from micros_tooling.config.service_generation import generate
        self.project.unlink()
        shared=self.directory/'standalone'
        generate(self.directory/'service.toml',shared)
        before={p.name:p.read_bytes() for p in shared.iterdir()}
        self.project.write_text((ROOT/'examples/typed-commands/micros.toml').read_text())
        generate_service_headers(self.project)
        service=load_project(self.project)['services'][0]
        built=Path(service['_contract']['directory'])/'generated'
        self.assertEqual(before,{p.name:p.read_bytes() for p in built.iterdir()})
        self.project.write_text(self.project.read_text().replace('["get_value", "set_value"]','["get_value"]'))
        generate_service_headers(self.project)
        self.assertEqual(before,{p.name:p.read_bytes() for p in built.iterdir()})
        adapter=Path(service['_interface']['directory'])/'generated/counter_bindings.c'
        self.assertIn('case 10: return true;',adapter.read_text())
        self.assertNotIn('case 11: return true;',adapter.read_text())

    def test_oversized_command_is_rejected_before_native_build(self):
        path=self.directory/'service.toml'
        path.write_text(path.read_text()+'\n[service.commands.too_big]\nargs = { a = { type="string", max_bytes=64 }, b = { type="string", max_bytes=64 } }\n')
        with self.assertRaisesRegex(ValueError,'wire bytes'):load_project(self.project)


if __name__ == '__main__':unittest.main()
