"""Authoring invariants: one owner, equivalent entry points, safe generation."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from micros_tooling.config.composition import toml
from micros_tooling.config.configuration import load_project, generate_service_headers, config_artifacts
from micros_tooling.config.service_generation import generate, definition
from micros_tooling.config.service_scaffold import create
from micros_tooling.config.artifacts import publish, build_inputs
from micros_tooling.config.generation_cli import run
from micros_tooling.config.contract_diff import compare
from micros_tooling.commands.schema import normalize, identity
from micros_tooling.commands.metadata import validate


class DeclarationModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'services/probe'
        self.source.mkdir(parents=True)
        (self.root / 'units').mkdir()
        (self.root / 'sample.proto').write_text('syntax="proto3"; message Sample { uint32 value=1; }')
        (self.root / 'interface.toml').write_text(toml({'interface': dict(interface='example.sample', major=1, minor=0, schema='sample.proto')}))
        self.model = dict(name='example.probe', version='1.0.0', build=dict(api='probe', lifecycle='hooks', sources=['src/service.c']),
            types=dict(Color=dict(type='enum', choices=['red', 'green']), Level=dict(type='uint32', min=0, max=10)),
            config_schema=dict(color=dict(type='Color', default='red'), level=dict(type='Level', default=5)),
            hardware=dict(led=dict(direction='output')), timers=dict(sample={}),
            publications=dict(output=dict(interface='../../interface.toml', policy='stream')),
            commands=dict(set_color=dict(description='Choose a color', args=dict(color='Color'), returns=dict(color='Color'))))
        self.document = dict(unit=dict(device_id='aabbccddeeff'), board=dict(profile='esp32', flash_mb=4),
            services=dict(probe=dict(source='../services/probe', contract='service.toml', memory=dict(arena='RAM'),
                gpio_bindings=dict(led=dict(pin=14)), publications=dict(output=dict(channel='samples')))),
            channels=dict(samples=dict(key=3, name='samples', depth=4, max_payload=32)))
        self.unit = self.root / 'units/aabbccddeeff.toml'
        self.contract = self.source / 'service.toml'
        self.write()

    def write(self):
        self.contract.write_text(toml({'service': self.model}))
        self.unit.write_text(toml(self.document))

    def contents(self, directory):
        return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob('*') if p.is_file()}

    def test_service_types_keep_config_encoding_and_command_values_identical(self):
        service = load_project(self.unit)['services'][0]
        config = service['_configuration']
        _, encoded = config_artifacts('probe', config['definition'], {})
        self.assertEqual(config['definition']['fields']['color']['choices'], service['_commands']['commands']['set_color']['args']['color']['choices'])
        self.model['config_schema'] = dict(color=dict(type='enum', choices=['red', 'green'], default='red'), level=dict(type='uint32', min=0, max=10, default=5))
        self.write()
        legacy = load_project(self.unit)['services'][0]['_configuration']
        self.assertEqual(encoded, config_artifacts('probe', legacy['definition'], {})[1])

    def test_local_type_file_updates_every_use_within_the_service(self):
        inline = definition(self.contract)[1]
        library = self.source/'types.toml'
        library.write_text(toml({'types': self.model['types']}))
        self.model['types'] = 'types.toml'
        self.write()
        self.assertEqual(inline, definition(self.contract)[1])
        before = load_project(self.unit)['services'][0]
        library.write_text(library.read_text().replace('["red", "green"]', '["green", "red"]'))
        after = load_project(self.unit)['services'][0]
        fields = after['_configuration']['definition']['fields']
        self.assertEqual(fields['color']['choices'], ['green', 'red'])
        self.assertEqual(fields['color']['choices'], after['_commands']['commands']['set_color']['args']['color']['choices'])
        self.assertNotEqual(before['_commands']['contract_id'], after['_commands']['contract_id'])

    def test_type_files_cannot_escape_the_owning_service(self):
        external = self.root/'types.toml'
        external.write_text(toml({'types': self.model['types']}))
        sibling = self.source.parent/'other'
        sibling.mkdir()
        (sibling/'types.toml').write_text(external.read_text())
        (self.source/'types.toml').symlink_to(external)
        (self.source/'linked').symlink_to(sibling, target_is_directory=True)
        for reference in ('../../types.toml', '../other/types.toml', str(external),
                          'types.toml', 'linked/types.toml'):
            with self.subTest(reference=reference):
                self.model['types'] = reference
                self.write()
                for operation in (lambda: generate(self.contract, self.root/'out'),
                                  lambda: load_project(self.unit)):
                    with self.assertRaisesRegex(ValueError, 'types file must remain inside this service directory') as caught:
                        operation()
                    self.assertEqual(caught.exception.path, str(self.contract))
                    self.assertIsNotNone(caught.exception.line)
                self.assertFalse((self.root/'out').exists())

    def test_same_named_types_in_other_services_evolve_independently(self):
        other = self.source.parent/'other'
        other.mkdir()
        model = copy.deepcopy(self.model)
        model['name'] = 'example.other'
        model['build']['api'] = 'other'
        model['hardware'] = {}
        other_contract = other/'service.toml'
        other_contract.write_text(toml({'service': model}))
        self.document['services']['other'] = copy.deepcopy(self.document['services']['probe'])
        self.document['services']['other']['source'] = '../services/other'
        self.document['services']['other'].pop('gpio_bindings')
        self.write()
        before = load_project(self.unit)['services'][1]
        generate(other_contract, self.root/'other-generated')
        generated = self.contents(self.root/'other-generated')
        self.model['types']['Color']['choices'] = ['green', 'red', 'blue']
        self.model['types']['Level']['max'] = 20
        self.write()
        changed, unchanged = load_project(self.unit)['services']
        self.assertEqual(changed['_configuration']['definition']['fields']['color']['choices'], ['green', 'red', 'blue'])
        self.assertEqual(changed['_configuration']['definition']['fields']['level']['max'], 20)
        self.assertEqual(unchanged['_configuration'], before['_configuration'])
        self.assertEqual(unchanged['_commands'], before['_commands'])
        generate(other_contract, self.root/'other-generated')
        self.assertEqual(generated, self.contents(self.root/'other-generated'))

    def test_batch_generation_failure_preserves_all_previous_services(self):
        with contextlib.redirect_stdout(io.StringIO()): run(self.root)
        before = self.contents(self.root/'build')
        self.model['commands']['set_color']['description'] = 'Changed documentation'
        self.write()
        broken = self.root/'services/zz_broken'
        broken.mkdir()
        (broken/'service.toml').write_text('[service]\nname="broken"\n')
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(io.StringIO()): run(self.root)
        self.assertEqual(before, self.contents(self.root/'build'))

    def test_authored_schema_cannot_be_shadowed_by_generated_rpc_filename(self):
        (self.root/'probe_rpc_request.proto').write_text((self.root/'sample.proto').read_text())
        interface = self.root/'interface.toml'
        interface.write_text(interface.read_text().replace('sample.proto', 'probe_rpc_request.proto'))
        with self.assertRaisesRegex(ValueError, 'Conflicting service schemas'):
            generate(self.contract, self.root/'generated')
        self.assertFalse((self.root/'generated').exists())

    def test_generation_and_composition_reject_the_same_unknown_build_field(self):
        self.model['build']['typo'] = True
        self.write()
        for operation in (lambda: generate(self.contract, self.root/'out'), lambda: load_project(self.unit)):
            with self.assertRaisesRegex(ValueError, 'unknown fields typo') as caught: operation()
            self.assertIn('service.toml', str(caught.exception))
            self.assertIsNotNone(caught.exception.line)
        self.assertFalse((self.root/'out').exists())

    def test_generation_and_composition_reject_unknown_types_and_bad_defaults(self):
        for change in ('type', 'default'):
            original = copy.deepcopy(self.model)
            self.model['config_schema']['level'][change] = 'Missing' if change == 'type' else 100
            self.write()
            for operation in (lambda: generate(self.contract, self.root/'out'), lambda: load_project(self.unit)):
                with self.assertRaises(ValueError): operation()
            self.model = original

    def test_generated_type_and_hook_collisions_fail_in_both_entry_points(self):
        for change in ('type', 'hook', 'rpc'):
            original = copy.deepcopy(self.model)
            if change == 'type': self.model['types']['Context'] = dict(type='uint32')
            else:
                name = 'start' if change == 'hook' else 'rpc_request'
                self.model['subscriptions'] = {name: dict(self.model['publications']['output'])}
            self.write()
            for operation in (lambda: generate(self.contract, self.root/'out'), lambda: load_project(self.unit)):
                with self.assertRaisesRegex(ValueError, 'colli|reserved'): operation()
            self.model = original

    def test_compose_and_failed_compose_never_write_output(self):
        self.document['services']['probe']['expose_commands'] = ['set_color']
        self.write()
        before = self.contents(self.root)
        load_project(self.unit)
        self.assertEqual(before, self.contents(self.root))
        self.document['services']['probe']['config'] = dict(level=99)
        self.write()
        before = self.contents(self.root)
        with self.assertRaisesRegex(ValueError, 'level'): generate_service_headers(self.unit)
        self.assertEqual(before, self.contents(self.root))

    def test_depth_and_unit_choices_do_not_change_service_interfaces(self):
        generate_service_headers(self.unit)
        recipe = load_project(self.unit)
        service = recipe['services'][0]
        common = Path(service['_contract']['directory'])/'generated'
        before = self.contents(common)
        self.document['channels']['samples']['depth'] = 8
        self.document['channels']['samples']['key'] = 6
        self.document['services']['probe']['gpio_bindings']['led']['pin'] = 15
        self.document['services']['probe']['config'] = dict(level=9)
        self.write()
        generate_service_headers(self.unit)
        self.assertEqual(before, self.contents(common))
        after = load_project(self.unit)['services'][0]
        self.assertEqual(after['channels'][0]['depth'], 8)
        self.assertEqual(after['_interface']['gpio'][0]['direction'], 'output')
        self.assertEqual(after['capabilities']['timers'], 1)
        sources, includes = build_inputs(after)
        self.assertIn(common/'probe_ipc.c', sources)
        self.assertEqual(includes, [common])

    def test_minimum_depth_wrong_policy_and_duplicate_metadata_are_rejected(self):
        for edit, message in ((dict(depth=0), 'depth'), (dict(policy='latest'), 'require'),
                              (dict(interface='example.sample'), 'metadata belongs')):
            original = copy.deepcopy(self.document)
            self.document['channels']['samples'].update(edit)
            self.write()
            with self.assertRaisesRegex(ValueError, message): load_project(self.unit)
            self.document = original

    def test_exact_schema_safety_is_preserved_across_references(self):
        other = self.root/'other'
        other.mkdir()
        changed = copy.deepcopy(self.model)
        changed['name'] = 'example.other'
        changed['hardware'] = {}
        changed['build']['api'] = 'other'
        changed.pop('publications')
        changed['subscriptions'] = dict(input=dict(interface='interface.toml', policy='stream'))
        (other/'sample.proto').write_text('syntax="proto3"; message Sample { uint64 value=1; }')
        (other/'interface.toml').write_text((self.root/'interface.toml').read_text())
        (other/'service.toml').write_text(toml({'service': changed}))
        self.document['services']['other'] = dict(source='../other', contract='service.toml', memory=dict(arena='RAM'), subscriptions=dict(input=dict(channel='samples')))
        self.write()
        with self.assertRaisesRegex(ValueError, 'conflicting interface'): load_project(self.unit)

    def test_contract_directory_basenames_do_not_collide(self):
        second = self.root/'dependency/probe'
        second.mkdir(parents=True)
        model = copy.deepcopy(self.model)
        model['name'] = 'example.second'
        model['build']['api'] = 'second'
        model['hardware'] = {}
        model['publications'] = {}
        (second/'service.toml').write_text(toml({'service': model}))
        self.document['services']['second'] = dict(source='../dependency/probe', contract='service.toml', memory=dict(arena='RAM'))
        self.write()
        recipe = load_project(self.unit)
        owners = [s['_contract']['directory'] for s in recipe['services']]
        self.assertEqual(len(set(owners)), 2)
        generate_service_headers(self.unit)
        self.assertTrue((Path(owners[0])/'generated/probe_hooks.h').exists())
        self.assertTrue((Path(owners[1])/'generated/second_hooks.h').exists())

    def test_output_owner_rejects_reuse_and_cleans_only_its_manifest(self):
        directory = self.root/'output'
        publish([(directory, 'one', {'one.h':'/* Generated from one */'})])
        (directory/'unrelated.h').write_text('/* Generated from someone else */')
        before = self.contents(directory)
        with self.assertRaisesRegex(ValueError, 'belongs'):
            publish([(directory, 'two', {'two.h':'/* Generated from two */'})])
        self.assertEqual(before, self.contents(directory))
        publish([(directory, 'one', {'new.h':'/* Generated from one */'})])
        self.assertFalse((directory/'one.h').exists())
        self.assertTrue((directory/'unrelated.h').exists())

    def test_all_destinations_are_preflighted_before_any_output(self):
        directory = self.root/'output'
        directory.mkdir()
        (directory/'owned.c').write_text('handwritten')
        with self.assertRaisesRegex(ValueError, 'non-generated'):
            publish([(self.root/'first', 'one', {'one.h':'/* Generated from one */'}),
                     (directory, 'two', {'owned.c':'/* Generated from two */'})])
        self.assertFalse((self.root/'first').exists())
        self.assertEqual((directory/'owned.c').read_text(), 'handwritten')

    def test_publication_failure_rolls_back_existing_outputs(self):
        import os
        directory = self.root/'output'
        publish([(directory, 'one', {'one.h':'/* Generated from old */'})])
        before = self.contents(directory)
        original = os.replace
        failed = False
        def fail_once(source, target):
            nonlocal failed
            if Path(target).name == 'two.h' and not failed:
                failed = True
                raise OSError('injected publication failure')
            return original(source, target)
        with patch('micros_tooling.config.artifacts.os.replace', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'injected'):
                publish([(directory, 'one', {'one.h':'/* Generated from new */', 'two.h':'/* Generated from new */'})])
        self.assertEqual(before, self.contents(directory))

    def test_generation_json_and_text_select_identical_contracts(self):
        with contextlib.redirect_stdout(io.StringIO()) as text:
            plain = run(self.root)
        before = self.contents(self.root/'build')
        with contextlib.redirect_stdout(io.StringIO()) as text:
            structured = run(self.root, json_output=True)
        self.assertEqual(plain, structured)
        self.assertEqual(json.loads(text.getvalue()), structured)
        self.assertEqual(before, self.contents(self.root/'build'))

    def test_typed_hooks_named_timer_and_documentation_compile(self):
        create(self.contract)
        output = self.root/'generated'
        generate(self.contract, output)
        header = (output/'probe_hooks.h').read_text()
        self.assertIn('probe_color_t arg_color', header)
        self.assertIn('Choose a color', header)
        self.assertIn('red | green', header)
        self.assertIn('probe_timer_sample_open', header)
        self.assertIn('timer_sample', (output/'probe_lifecycle.c').read_text())
        result = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsyntax-only',
            '-I'+str(ROOT/'src/sdk/abi/include'), '-I'+str(ROOT/'src/sdk/abi/internal'),
            '-I'+str(ROOT/'src/third_party/nanopb'), '-I'+str(output),
            str(self.source/'src/service.c'), str(output/'probe_lifecycle.c')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_documentation_does_not_change_v2_identity_and_legacy_is_readable(self):
        commands = normalize(self.model['commands'], self.model['types'])
        changed = copy.deepcopy(commands)
        changed['set_color']['description'] = 'Different prose'
        self.assertEqual(identity(commands, ['set_color']), identity(changed, ['set_color']))
        self.assertNotEqual(identity(commands, ['set_color'], format=1), identity(changed, ['set_color'], format=1))
        for version in (1, 2):
            value = dict(format=version, api='probe', commands=commands, exposed=['set_color'],
                         contract_id=identity(commands, ['set_color'], format=version), request_key=1, response_key=2)
            validate(value)
            value['commands'] = changed
            if version == 1:
                with self.assertRaisesRegex(ValueError, 'identity mismatch'): validate(value)
            else: validate(value)

    def test_git_diff_reports_semantics_and_only_changed_hook_stubs(self):
        def git(*args):
            return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)
        git('init', '-q')
        git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'baseline')
        self.model['commands']['set_color']['description'] = 'Updated prose'
        self.write()
        report = compare(self.contract, 'HEAD')
        self.assertTrue(report['changes'])
        self.assertTrue(all(c['category']=='documentation' for c in report['changes']))
        self.assertEqual(report['stubs'], {})
        self.model['commands']['set_color']['args']['persist'] = 'bool'
        self.write()
        report = compare(self.contract, 'HEAD')
        self.assertEqual(set(report['stubs']), {'probe_handle_set_color'})
        self.assertIn('arg_persist', report['stubs']['probe_handle_set_color'])


if __name__ == '__main__': unittest.main()
