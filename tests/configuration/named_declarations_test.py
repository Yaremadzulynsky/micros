"""Exercise named channel assembly and service-owned pin requirements end to end."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from micros_tooling.config.composition import toml
from micros_tooling.config.configuration import load_project, generate_service_headers
from micros_tooling.config.declarations import contract
from micros_tooling.config.service_generation import generate
from micros_tooling.config.chips import unit_pin_listing


class NamedDeclarationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'units').mkdir()
        for name in ('sensor', 'logger'):
            (self.root / 'services' / name).mkdir(parents=True)
        (self.root / 'sample.proto').write_text('syntax="proto3"; message Sample { uint32 value=1; }')
        self.interface = dict(interface=dict(interface='example.sample', schema='sample.proto'),
                              delivery=dict(policy='stream'))
        self.sensor = dict(name='example.sensor', version='1.0.0',
            build=dict(api='sensor', sources=['src/service.c']),
            config=dict(interval=dict(type='uint32', default=20, min=1, max=1000)),
            pins=dict(button=dict(type='pullup'), temperature=dict(type='analog')),
            timers=['sample', 'timeout'],
            publications=dict(readings=dict(interface='../../interface.toml')))
        self.logger = dict(name='example.logger', version='1.0.0',
            build=dict(api='logger', sources=['src/service.c']),
            subscriptions=dict(readings=dict(interface='../../interface.toml', min_depth=4)))
        self.unit = dict(unit=dict(device_id='aabbccddeeff'),
            board=dict(profile='adafruit_feather_esp32_v2'),
            services=dict(sensor=dict(source='../services/sensor', contract='service.toml',
                                      pins=dict(button=38, temperature=34), memory=dict(arena='RAM')),
                          logger=dict(source='../services/logger', contract='service.toml', memory=dict(arena='RAM'))),
            channels=dict(readings=dict(depth=8)))
        self.path = self.root / 'units/aabbccddeeff.toml'
        self.write()

    def write(self):
        (self.root / 'interface.toml').write_text(toml(self.interface))
        for name in ('sensor', 'logger'):
            (self.root / f'services/{name}/service.toml').write_text(toml(dict(service=getattr(self, name))))
        self.path.write_text(toml(self.unit))

    def load(self):
        self.write()
        return load_project(self.path)

    def test_assembly_resolves_pins_channels_settings_and_timers(self):
        result = self.load()
        sensor, logger = result['services']
        self.assertEqual(sensor['_configuration']['definition']['fields']['interval']['default'], 20)
        self.assertEqual(sensor['capabilities']['timers'], 2)
        self.assertEqual(sensor['channels'][0]['key'], logger['channels'][0]['key'])
        self.assertEqual(sensor['channels'][0]['name'], 'readings')
        self.assertEqual(sensor['channels'][0]['depth'], 8)
        self.assertEqual(sensor['channels'][0]['policy'], 'stream')
        self.assertEqual([g['pin'] for g in sensor['_interface']['gpio']], [38, 34])
        listing = unit_pin_listing(self.path)
        button = next(p for p in listing['pins'] if p['pin'] == 38)
        self.assertEqual(button['external_pull'], 'up')
        self.assertEqual(button['configured']['owner'], 'sensor.button')

    def test_depth_derivation_and_explicit_rejection(self):
        self.unit['channels']['readings'] = {}
        self.assertEqual(self.load()['services'][0]['channels'][0]['depth'], 4)
        self.unit['channels']['readings']['depth'] = 2
        with self.assertRaisesRegex(ValueError, 'at least 4'): self.load()

    def test_missing_or_misspelled_channel_is_not_created(self):
        self.unit['channels'] = dict(reading={})
        with self.assertRaisesRegex(ValueError, 'required channel.*readings'): self.load()

    def test_named_channels_reject_manual_aliases_and_duplicate_metadata(self):
        original = copy.deepcopy(self.unit)
        for change in ('alias', 'name', 'policy', 'schema'):
            self.unit = copy.deepcopy(original)
            if change == 'alias':
                self.unit['services']['logger']['subscriptions'] = dict(readings=dict(channel='other'))
            else:
                self.unit['channels']['readings'][change] = 'other'
            with self.subTest(change=change), self.assertRaises(ValueError): self.load()

    def test_interface_owns_policy_and_has_no_authored_versions(self):
        self.sensor['publications']['readings']['policy'] = 'latest'
        with self.assertRaisesRegex(ValueError, 'belongs to the shared interface'): self.load()
        self.sensor['publications']['readings'].pop('policy')
        self.interface['interface']['major'] = 1
        with self.assertRaisesRegex(ValueError, 'unknown fields major'): self.load()

    def test_schema_and_delivery_mismatches_are_rejected(self):
        self.logger['subscriptions']['readings']['interface'] = '../../other.toml'
        other = copy.deepcopy(self.interface)
        other['delivery']['policy'] = 'latest'
        self.logger['subscriptions']['readings'].pop('min_depth')
        (self.root / 'other.toml').write_text(toml(other))
        with self.assertRaisesRegex(ValueError, 'incompatible delivery'): self.load()
        other = copy.deepcopy(self.interface)
        other['interface']['schema'] = 'other.proto'
        (self.root / 'other.proto').write_text('syntax="proto3"; message Sample { uint64 value=1; }')
        (self.root / 'other.toml').write_text(toml(other))
        with self.assertRaisesRegex(ValueError, 'conflicting interface'): self.load()

    def test_pin_requirements_reject_impossible_wiring(self):
        for role, pin, error in [('button', 4, 'not yet supported'),
                                 ('temperature', 13, 'ADC1 only'),
                                 ('temperature', 21, 'not an analog input')]:
            original = self.unit['services']['sensor']['pins'][role]
            self.unit['services']['sensor']['pins'][role] = pin
            with self.subTest(role=role, pin=pin), self.assertRaisesRegex(ValueError, error): self.load()
            self.unit['services']['sensor']['pins'][role] = original
        self.sensor['pins']['button']['type'] = 'pulldown'
        with self.assertRaisesRegex(ValueError, 'external pull-up'): self.load()

    def test_pin_map_must_be_complete_and_unknown_fields_fail(self):
        self.unit['services']['sensor']['pins'].pop('temperature')
        with self.assertRaisesRegex(ValueError, 'exactly'): self.load()
        self.unit['services']['sensor']['pins']['temperature'] = 34
        self.sensor['pins']['button']['pull'] = 'none'
        with self.assertRaisesRegex(ValueError, 'unknown fields pull'): self.load()

    def test_legacy_resource_binding_cannot_bypass_new_pin_requirement(self):
        self.sensor['pins'] = dict(button=dict(type='pullup'))
        selection = self.unit['services']['sensor']
        selection.pop('pins')
        selection['gpio_bindings'] = dict(button='external_button')
        self.unit['board']['gpio'] = dict(external_button=dict(pin=4, direction='input'))
        with self.assertRaisesRegex(ValueError, 'not yet supported'): self.load()

    def test_duplicate_sources_and_timer_names_are_rejected(self):
        for key, value in [('config_schema', {}), ('hardware', {}), ('timers', ['sample', 'sample'])]:
            original = copy.deepcopy(self.sensor)
            self.sensor[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'duplicates|unique timer'): self.load()
            self.sensor = original

    def test_multiple_instances_share_channel_but_have_independent_pin_roles(self):
        self.sensor['pins'] = dict(temperature=dict(type='analog'))
        self.unit['services']['sensor']['pins'] = dict(temperature=34)
        second = copy.deepcopy(self.unit['services']['sensor'])
        second['pins']['temperature'] = 36
        second['name'] = 'example.second'
        self.unit['services']['second'] = second
        result = self.load()
        publishers = [s for s in result['services'] if s['channels'][0]['access'] == 'publish']
        self.assertEqual(len(publishers), 2)
        self.assertEqual(publishers[0]['channels'][0]['key'], publishers[1]['channels'][0]['key'])
        self.assertNotEqual(publishers[0]['capabilities']['gpio'], publishers[1]['capabilities']['gpio'])
        second['pins']['temperature'] = 34
        with self.assertRaisesRegex(ValueError, 'already assigned'): self.load()

    def test_disabled_services_do_not_allocate_or_require_resources(self):
        self.unit['services']['sensor']['enabled'] = False
        self.unit['services']['sensor']['pins']['button'] = 999
        result = self.load()
        self.assertEqual(len(result['services']), 1)
        self.assertEqual(result['board']['gpio'], [])

    def test_generated_analog_helper_calls_analog_abi_and_timer_helper_runs(self):
        self.load()
        generate_service_headers(self.path)
        result = load_project(self.path)
        sensor = result['services'][0]
        output = Path(sensor['_contract']['directory']) / 'generated'
        binding = Path(sensor['_interface']['directory']) / 'generated/sensor_bindings.c'
        source = self.root / 'test.c'
        source.write_text('''#include <assert.h>
#include "sensor_resources.h"
static micros_result_t analog(micros_context_t *c, micros_handle_t h, uint32_t *v) {
    (void)c; assert(h == 42); *v = 1234; return MICROS_OK;
}
static micros_result_t timer(micros_context_t *c, uint64_t delay, uint64_t period,
    micros_timer_callback_t cb, void *data, micros_handle_t *h) {
    (void)c; (void)cb; (void)data; assert(delay == 10 && period == 20); *h=7; return MICROS_OK;
}
int main(void) {
    micros_api_t api = {.gpio_read_analog=analog, .timer_open=timer};
    micros_service_args_t args = {.api=&api};
    uint32_t value=0; micros_handle_t handle=0;
    assert(sensor_temperature_read(&args, 42, &value) == MICROS_OK && value == 1234);
    assert(sensor_timer_sample_open(&args, 10, 20, 0, 0, &handle) == MICROS_OK && handle == 7);
    return 0;
}
''')
        executable = self.root / 'test'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-I'+str(ROOT/'src/sdk/abi/include'), '-I'+str(output),
                        str(source), str(binding), '-o', str(executable)], check=True, capture_output=True)
        subprocess.run([str(executable)], check=True, capture_output=True)

    def test_service_artifacts_do_not_depend_on_board_choices(self):
        path = self.root / 'services/sensor/service.toml'
        output = self.root / 'generated'
        generate(path, output)
        before = {p.name:p.read_bytes() for p in output.iterdir() if p.is_file()}
        self.unit['channels']['readings']['depth'] = 4
        self.unit['services']['sensor']['pins']['temperature'] = 36
        self.unit['services']['sensor']['config'] = dict(interval=100)
        self.load()
        generate(path, output)
        self.assertEqual(before, {p.name:p.read_bytes() for p in output.iterdir() if p.is_file()})


if __name__ == '__main__': unittest.main()
