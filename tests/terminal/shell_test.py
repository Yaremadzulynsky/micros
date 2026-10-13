"""Exercise interactive recovery, bounded polling, discovery and no write retries."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from micros_tooling.terminal.shell import Shell, line_editor, safe_text, readline_backend
from micros_tooling.terminal.client import DeviceClient, pick_device
from micros_tooling.communication.remote import RemoteRejected
from micros_tooling.storage.workspace import Workspace


def binding():
    from google.protobuf import descriptor_pb2
    f = descriptor_pb2.FileDescriptorProto(name='value.proto', syntax='proto3')
    m = f.message_type.add(name='Value')
    m.field.add(name='value', number=1, type=13, label=1)
    return dict(service='example.shell', version='1.0.0', instance=0, max_payload=16,
                port=dict(name='value', key=1, descriptor=base64.b64encode(f.SerializeToString()).decode()))


def command_binding():
    from micros_tooling.commands.schema import normalize, identity
    commands=normalize({'set':dict(args=dict(value=dict(type='uint32', min=0, max=100)))})
    return dict(service='example.shell',version='1.0.0',service_index=1,instance=0,
                contract=dict(format=2,api='demo',commands=commands,exposed=['set'],contract_id=identity(commands,['set']),request_key=1,response_key=2))


def status():
    return dict(identity=dict(device_id='0123456789ab', base_sha256='a'*64), platform='esp32',
                activation=dict(sequence=1, good_sha256='b'*64, pending=0), service_boot='123', heap=1234,
                services=[dict(name='example.shell', state='Running', result=0, steps=4, callbacks=0)],
                channel_ports=[binding()], service_commands=[command_binding()])


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(name='client')
        self.client.name = 'desk'
        self.client.identity = '0123456789ab'
        self.client.inspection_supported = True
        self.client.status.return_value = status()
        self.output = io.StringIO()
        self.sleep = Mock()
        self.shell = Shell(self.client, output=self.output, sleep=self.sleep)

    def test_watch_sleep_bounds_interrupt_latency_without_shortening_interval(self):
        from micros_tooling.terminal.shell import interruptible_sleep
        clock = [0.0]
        def advance(seconds):
            clock[0] += seconds
        with patch('micros_tooling.terminal.shell.time.monotonic', side_effect=lambda: clock[0]), \
             patch('micros_tooling.terminal.shell.time.sleep', side_effect=advance) as sleep:
            interruptible_sleep(1.1)
        self.assertAlmostEqual(clock[0], 1.1)
        self.assertTrue(all(0 < call.args[0] <= .25 for call in sleep.call_args_list))
        with patch('micros_tooling.terminal.shell.time.sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                interruptible_sleep(10)

    def test_interactive_bad_input_and_ctrl_c_keep_prompt_alive(self):
        lines = iter(['nonsense', 'watch --count 2', 'services', 'exit'])
        self.sleep.side_effect = KeyboardInterrupt
        self.assertEqual(self.shell.interact(lambda _: next(lines)), 0)
        self.assertIn('Unknown command', self.output.getvalue())
        self.assertIn('Interrupted', self.output.getvalue())
        self.assertIn('example.shell', self.output.getvalue())

    def test_ctrl_c_at_prompt_and_eof(self):
        read = Mock(side_effect=[KeyboardInterrupt, EOFError])
        self.assertEqual(self.shell.interact(read), 0)
        self.assertEqual(read.call_count, 2)

    def test_watch_reconnects_after_transient_outage_and_is_bounded(self):
        self.client.status.side_effect = [OSError('offline'), status(), status()]
        self.shell.execute('watch --interval .25 --count 3 services')
        self.assertEqual(self.client.status.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)
        self.assertIn('Connection unavailable', self.output.getvalue())
        self.assertIn('Connected:', self.output.getvalue())

    def test_watch_does_not_retry_authentication_or_certificate_errors(self):
        for error in (RemoteRejected(401,b'no'), ssl.SSLCertVerificationError('bad cert')):
            self.client.status.reset_mock(side_effect=True)
            self.client.status.side_effect = error
            self.assertEqual(self.shell.run_line('watch --count 2')[1], 1)
            self.assertEqual(self.client.status.call_count, 1)
        self.sleep.assert_not_called()

    def test_watch_rejects_invalid_bounds_before_network(self):
        for arguments in ('--interval nan', '--interval inf', '--interval 0', '--count 0', '--count -1'):
            self.assertEqual(self.shell.run_line('watch '+arguments)[1], 1)
        self.client.status.assert_not_called()

    def test_typed_commands_and_fields_are_discoverable_and_complete(self):
        self.shell.execute('commands')
        self.assertIn('value:', self.output.getvalue())
        readline = readline_backend()
        for prefix, text, expected in [('call ', 'ex', 'example.shell'), ('call example.shell ', 's', 'set'),
                                       ('call example.shell set ', 'v', 'value=')]:
            with patch.object(readline, 'get_line_buffer', return_value=prefix), patch.object(readline, 'get_begidx', return_value=len(prefix)):
                self.assertEqual(self.shell.complete(text, 0), expected)
        self.assertFalse(self.client.call.called)

    def test_release_change_refreshes_completion(self):
        self.shell.execute('commands')
        newer = status(); newer['activation']['sequence']=2; newer['channel_ports']=[]
        self.client.status.return_value = newer
        self.shell.execute('commands')
        self.assertFalse(self.shell.bindings)
        self.assertIn('application changed', self.output.getvalue())

    def test_no_retry_after_uncertain_command_and_duplicate_fields_rejected(self):
        self.client.invoke.side_effect = RemoteRejected(504,b'outcome_unknown')
        self.assertEqual(self.shell.run_line('call example.shell set value=3')[1], 1)
        self.client.invoke.assert_called_once_with('example.shell','set',{'value':'3'})
        self.assertIn('not retried', self.output.getvalue())
        self.assertEqual(self.shell.run_line('call example.shell set value=3 value=4')[1], 1)
        self.assertEqual(self.client.invoke.call_count,1)

    def test_json_status_is_parseable_and_service_selection_works(self):
        self.shell.execute('status --json')
        self.assertEqual(json.loads(self.output.getvalue())['heap'],1234)
        self.output.seek(0); self.output.truncate()
        self.shell.execute('services example.shell --json')
        self.assertEqual(json.loads(self.output.getvalue())['name'],'example.shell')

    def test_log_follow_ctrl_c_returns_to_shell(self):
        def events(*args):
            yield dict(event='logs',logs='hello\n')
            raise KeyboardInterrupt
        with patch('micros_tooling.terminal.shell.follow_logs',side_effect=events):
            self.assertEqual(self.shell.run_line('logs --follow'),(True,130))
        self.assertTrue(self.shell.execute('help'))

    def test_telemetry_generator_closed_on_interruption(self):
        closed=[]
        def samples(*args, **kwargs):
            try:
                yield {'state':'sample'}
                raise KeyboardInterrupt
            finally:
                closed.append(True)
        self.client.samples.side_effect=samples
        self.assertEqual(self.shell.run_line('follow example.shell value')[1],130)
        self.assertEqual(closed,[True])

    def test_history_and_terminal_escapes(self):
        self.assertEqual(safe_text('\x1b]52;clipboard\x07'), '\\x1b]52;clipboard\\x07')
        self.shell.execute('help'); self.shell.execute('history')
        self.assertIn('1  help', self.output.getvalue())
        readline = readline_backend()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'history'
            with line_editor(self.shell,path):
                readline.add_history('services')
            self.assertEqual(path.read_text(),'services\n')
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            other=Path(directory)/'other'; other.write_text('do not touch')
            path.unlink(); path.symlink_to(other)
            with line_editor(self.shell,path):
                readline.add_history('help')
            self.assertEqual(other.read_text(),'do not touch')

    def test_script_mode_is_offline_for_help_and_fails_fast(self):
        for args,code in [(['-c','help'],0), (['-c','bad','-c','help'],1)]:
            result=subprocess.run([sys.executable,str(ROOT/'tools/micros.py'),'shell',*args], capture_output=True,text=True)
            self.assertEqual(result.returncode,code,result.stderr)
        result=subprocess.run([str(ROOT/'micros'),'shell'], input='help\nexit\n', capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('Connected:',result.stdout)


class PickerTests(unittest.TestCase):
    def test_lists_online_first_reprompts_and_selects(self):
        devices=[dict(name='offline',device_id='f'*12,online=False),
                 dict(name='desk',device_id='a'*12,online=True)]
        output=io.StringIO()
        selected=pick_device(devices,ask=Mock(side_effect=['bad','0','1']),output=output)
        self.assertEqual(selected['name'],'desk')
        self.assertIn('1. desk',output.getvalue())
        self.assertIn('offline',output.getvalue())

    def test_one_device_still_prompts_and_cancel_is_supported(self):
        devices=[dict(name='desk',device_id='a'*12,online=True)]
        ask=Mock(return_value='1')
        self.assertEqual(pick_device(devices,ask=ask,output=io.StringIO()),devices[0])
        ask.assert_called_once()
        with self.assertRaises(KeyboardInterrupt):
            pick_device(devices,ask=lambda _: 'q',output=io.StringIO())

    def test_client_uses_picker_only_for_initial_interactive_selection(self):
        client=DeviceClient(Mock(),None,interactive=True)
        device=dict(name='desk',device_id='a'*12,online=True,last_seen=0)
        remote=Mock();remote.raw.return_value=json.dumps(dict(devices=[device]))
        with patch('micros_tooling.fleet.server.configured_remote',return_value=remote), \
             patch('micros_tooling.terminal.client.pick_device',return_value=device) as picker:
            client.connect();client.connect()
        picker.assert_called_once()
        self.assertEqual(client.identity,'a'*12)

    def test_noninteractive_device_access_requires_explicit_device(self):
        client=DeviceClient(Mock(),None)
        remote=Mock();remote.raw.return_value=json.dumps(dict(devices=[dict(name='desk',device_id='a'*12,online=True)]))
        with patch('micros_tooling.fleet.server.configured_remote',return_value=remote):
            with self.assertRaisesRegex(ValueError,'Specify -d'):
                client.connect()


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client=DeviceClient(Mock(),'desk')
        self.remote=Mock()
        self.remote.device_id='0123456789ab'
        self.client.remote=self.remote
        self.client.identity=self.remote.device_id
        self.remote.raw.return_value=json.dumps(status()).encode()

    def test_old_server_falls_back_to_existing_status_once(self):
        self.remote.raw.side_effect=RemoteRejected(404,b'unknown_route')
        self.remote.status.return_value=status()
        self.client.status(); self.client.status()
        self.assertEqual(self.remote.raw.call_count,1)
        self.assertEqual(self.remote.status.call_count,2)
        with self.assertRaisesRegex(ValueError,'updated management server'):
            self.client.binding('example.shell','value')

    def test_command_bound_to_live_release_and_no_retry(self):
        self.remote.raw.side_effect=[json.dumps(status()).encode(),TimeoutError('unknown')]
        with self.assertRaises(TimeoutError):
            self.client.invoke('example.shell','set',{'value':'42'})
        self.assertEqual(self.remote.raw.call_count,2)
        method,path,body=self.remote.raw.call_args.args
        self.assertEqual((method,path),('POST','/v1/commands/0123456789ab'))
        self.assertEqual(json.loads(body)['graph'],'b'*64)

    def test_wrong_device_and_bad_fields_never_dispatch(self):
        wrong=status();wrong['identity']['device_id']='f'*12
        self.remote.raw.return_value=json.dumps(wrong).encode()
        with self.assertRaisesRegex(ValueError,'identity changed'):
            self.client.status()
        self.remote.raw.return_value=json.dumps(status()).encode()
        for values in ({}, {'value':101},{'value':True},{'other':3}):
            self.remote.raw.reset_mock()
            with self.assertRaises(ValueError):self.client.invoke('example.shell','set',{k:str(v) for k,v in values.items()})
            self.assertEqual(self.remote.raw.call_count,1)

    def test_connect_pins_identity_across_rename_and_reconnect(self):
        self.client.remote=None; self.client.identity=None
        remote=Mock()
        remote.raw.return_value=json.dumps({'devices':[dict(device_id='0123456789ab', name='desk', online=False, last_seen=0)]})
        with patch('micros_tooling.fleet.server.configured_remote',return_value=remote):
            self.client.connect()
            remote.raw.return_value=json.dumps({'devices':[dict(device_id='0123456789ab', name='renamed', online=True, last_seen=0),
                                                                    dict(device_id='f'*12,name='desk',online=True,last_seen=0)]})
            self.client.connect()
        self.assertEqual(self.client.identity,'0123456789ab')
        self.assertEqual(self.client.name,'renamed')

    def test_reconnect_does_not_switch_a_saved_profile_to_another_board(self):
        with patch('micros_tooling.fleet.server.configured_remote', return_value=None), \
             patch('micros_tooling.deployment.diagnostics.connect', return_value=('desk', {'device_id':'f'*12}, Mock())):
            with self.assertRaisesRegex(ValueError, 'changed device identity'):
                self.client.connect()
        self.assertEqual(self.client.identity, '0123456789ab')

    def test_capture_cleanup_on_close_and_error(self):
        self.client.binding=Mock(return_value=(status(),{}))
        replies=[dict(reader='r',cursor=0),dict(cursor=1,events=[dict(state='sample',sample={'value':42})]),{}]
        with patch('micros_tooling.diagnostics.collect.stream',side_effect=replies) as stream:
            generator=self.client.samples('example.shell','value')
            self.assertEqual(next(generator)['sample']['value'],42)
            generator.close()
            self.assertEqual(stream.call_args.args[1],dict(action='close',reader='r'))
        with patch('micros_tooling.diagnostics.collect.stream',side_effect=[dict(reader='r',cursor=0),OSError('lost'),{}]) as stream:
            with self.assertRaises(OSError):list(self.client.samples('example.shell','value'))
            self.assertEqual(stream.call_args.args[1]['action'],'close')


if __name__=='__main__':unittest.main()
