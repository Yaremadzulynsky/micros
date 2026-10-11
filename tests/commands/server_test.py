"""Real authenticated HTTP routes, typed replies, correlation and uncertain outcomes."""
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'src'),str(ROOT/'tests/terminal')]
# Import the fixture under an unambiguous module name (this file is also server_test).
import importlib.util
spec=importlib.util.spec_from_file_location('terminal_server_fixture', ROOT/'tests/terminal/server_test.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
from micros_tooling.commands.schema import normalize, identity, descriptor
from micros_tooling.communication.protobuf import message_class
from micros_tooling.terminal.client import DeviceClient
from micros_tooling.terminal.shell import Shell
from micros_tooling.communication.remote import accepted
from server.commands import operate
DEVICE=fixture.DEVICE


class CommandServerTests(unittest.TestCase):
    request=fixture.ServerTests.request
    tearDown=fixture.ServerTests.tearDown

    def setUp(self):
        fixture.ServerTests.setUp(self)
        for i,service in enumerate(self.observed["services"]):service["instance"]=str(i+1)
        commands=normalize({'get_color':dict(returns=dict(color=dict(type='enum',choices=['red','blue']))),
                            'set_color':dict(args=dict(color=dict(type='enum',choices=['red','blue'])),returns=dict(color=dict(type='enum',choices=['red','blue']))),
                            'echo':dict(args=dict(text=dict(type='string',max_bytes=12),enabled='bool'),returns=dict(text=dict(type='string',max_bytes=12),enabled='bool'))})
        self.contract=dict(format=2,api='demo',commands=commands,exposed=sorted(commands),contract_id=identity(commands,sorted(commands)),request_key=1,response_key=2)
        binding=dict(service='example.shell',version='1.0.0',service_index=1,instance=0,contract=self.contract)
        self.binding=binding
        self.registry.management.accept_release_labels(dict(before=dict(identity=dict(base_sha256='a'*64)),
            plan=dict(services=[dict(name='board.network-bridge',version='1.0.0',permissions=dict(publish_mask=1)),
                                dict(name='example.shell',version='1.0.0',permissions=dict(publish_mask=2))],
                      channels=[dict(key=1,name='request'),dict(key=2,name='response')],service_commands=[binding]),
            banks={'0':dict(digest='b'*64)}))
        self.Request=message_class(descriptor('demo',commands))
        self.Response=message_class(descriptor('demo',commands,True))
        self.replies=[];self.handler_result=0;self.mode='normal';self.sessions=[]
        def command(device,operation,bank,slot,cursor,session,body):
            if operation==0:return 200,json.dumps(self.observed).encode()
            if operation in (8,9):
                self.sessions.append(operation)
                return 200,b'{}'
            self.assertEqual(operation,18)
            if body.startswith(b'IPC WRITE'):
                self.writes.append((session,body))
                message=self.Request.FromString(bytes.fromhex(body.decode().split()[-1]))
                name=message.WhichOneof('command')
                reply=self.Response(request_id=message.request_id,contract_id=message.contract_id,result=self.handler_result)
                if not self.handler_result:
                    output=getattr(reply,name);output.SetInParent()
                    if name=='get_color':output.color=0
                    elif name=='set_color':output.color=message.set_color.color
                    else:
                        output.text=message.echo.text;output.enabled=message.echo.enabled
                if self.mode=='wrong-contract':reply.contract_id^=1
                if self.mode=='wrong-command':reply.get_color.SetInParent()
                self.replies=[self.Response(request_id=1).SerializeToString(),reply.SerializeToString()]
                if self.mode=='malformed':self.replies=[b'\xff']
                if self.mode=='empty':self.replies=[]
                if self.mode=='restart':self.observed['service_boot']='new-boot'
                if self.mode=='disconnect':raise OSError('link lost after write')
                if self.mode=='ipc-error':return 200,b'{"reply":"IPC ERROR -5"}'
                return 200,b'{"reply":"IPC QUEUED 1"}'
            self.assertEqual(body,b'IPC READ 0 2')
            reply='IPC DATA 2 '+self.replies.pop(0).hex() if self.replies else 'IPC EMPTY 2'
            return 200,json.dumps(dict(reply=reply)).encode()
        self.registry.command.side_effect=command

    def payload(self,command='set_color',args=None):
        return dict(base='a'*64,graph='b'*64,service='example.shell',command=command,args={'color':'blue'} if args is None else args)

    def post(self,payload):
        code,body=self.request('POST','/v1/commands/'+DEVICE,json.dumps(payload).encode())
        return code,json.loads(body)

    def test_inspection_and_command_do_not_need_console(self):
        self.server.console = None
        code, raw = self.request('GET', '/v1/inspect/' + DEVICE)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)['service_commands'][0]['service'], 'example.shell')
        code, reply = self.post(self.payload())
        self.assertEqual(code, 200)
        self.assertEqual(reply['state'], 'completed')
        self.assertEqual(reply['values'], {'color': 'blue'})
        self.assertFalse(self.registry.management.active_devices)

    def test_console_job_and_command_share_operation_exclusion(self):
        with patch('server.console.threading.Thread'):
            job = self.server.console.submit(DEVICE, 'reboot', {})
        with self.assertRaisesRegex(ValueError, 'already running'):
            operate(self.registry.management, DEVICE, self.payload())
        self.assertFalse(self.writes)
        with patch('server.console.RegistryRemote', side_effect=ValueError('offline')):
            self.server.console.run(job, DEVICE, 'reboot', {})
        self.assertEqual(self.server.console.job(job)['state'], 'failed')
        self.assertFalse(self.registry.management.active_devices)
        code, reply = self.post(self.payload())
        self.assertEqual((code, reply['state']), (200, 'completed'))

    def test_shell_round_trip_enum_strings_booleans_and_zero_argument_command(self):
        outer=self
        class Transport:
            device_id=DEVICE
            def raw(self,method,path,body=b''):
                code,raw=outer.request(method,path,body);accepted(code,raw);return raw
        client=DeviceClient(None,'desk');client.remote=Transport();client.identity=DEVICE
        shell=Shell(client,output=io.StringIO())
        shell.execute('commands');self.assertIn('get_color',shell.output.getvalue())
        shell.execute('help call example.shell set_color');self.assertIn('red | blue',shell.output.getvalue())
        shell.execute('call example.shell set_color color=blue');self.assertIn('blue',shell.output.getvalue())
        shell.execute('call example.shell get_color');self.assertIn('red',shell.output.getvalue())
        shell.execute('call example.shell echo text="hello world" enabled=false')
        self.assertIn('hello world',shell.output.getvalue())
        self.assertEqual(len(self.writes),3)
        self.assertEqual(self.sessions,[8,9]*3)
        self.assertFalse(self.registry.management.active_devices)
        from micros_tooling.terminal.shell import readline_backend
        readline = readline_backend()
        prefix='call example.shell set_color '
        with patch.object(readline,'get_line_buffer',return_value=prefix+'color=b'), patch.object(readline,'get_begidx',return_value=len(prefix)):
            self.assertEqual(shell.complete('color=b',0),'color=blue')

    def test_large_release_metadata_fits_the_bounded_operator_route(self):
        fields={f'field_{i}':dict(type='enum',choices=[f'choice_{j}' for j in range(32)]) for i in range(4)}
        commands=normalize({f'command_{i}':dict(args=fields,returns=fields) for i in range(8)})
        contract=dict(self.contract,commands=commands,exposed=sorted(commands),contract_id=identity(commands,sorted(commands)))
        payload=dict(before=dict(identity=dict(base_sha256='a'*64)),
            plan=dict(services=[dict(name='board.network-bridge',version='1',permissions=dict(publish_mask=1)),dict(name='example.shell',version='1',permissions=dict(publish_mask=2))],
                      channels=[],service_commands=[dict(self.binding,contract=contract)]),banks={'0':dict(digest='c'*64)})
        wire=json.dumps(payload).encode()
        self.assertGreater(len(wire),16384)
        self.assertEqual(self.request('POST','/v1/release-labels',wire)[0],200)

    def test_bad_arguments_graph_and_exposure_rejected_before_write(self):
        for payload in [self.payload(args={'color':'green'}),self.payload(args={}),self.payload('missing'),
                        self.payload()|{'graph':'c'*64},self.payload('echo',{'text':'too long text here','enabled':True})]:
            with self.subTest(payload=payload):self.assertEqual(self.post(payload)[0],400)
        self.assertFalse(self.writes)
        self.assertFalse(self.registry.management.active_devices)

    def test_missing_instance_identity_rejects_before_write(self):
        self.observed['services'][1].pop('instance')
        code,reply=self.post(self.payload())
        self.assertEqual(code,400)
        self.assertIn('instance identities',reply['error'])
        self.assertFalse(self.writes)

    def test_handler_errors_are_distinct_from_unknown_outcome(self):
        self.handler_result=-2
        code,reply=self.post(self.payload())
        self.assertEqual(code,200);self.assertEqual(reply['state'],'failed');self.assertEqual(reply['result'],-2)
        self.assertNotIn('values',reply)
        self.assertEqual(len(self.writes),1)

    def test_uncertain_outcomes_never_retry_and_release_session(self):
        for mode in ('wrong-contract','wrong-command','malformed','restart','disconnect','ipc-error','empty'):
            self.mode=mode;self.writes.clear();self.sessions.clear()
            with self.subTest(mode=mode):
                reply=operate(self.registry.management,DEVICE,self.payload(),sleep=lambda _:None)
                self.assertEqual(reply['state'],'unknown')
                self.assertIn('not retried',reply['message'])
                self.assertEqual(len(self.writes),1)
                self.assertEqual(self.sessions,[8,9])
                self.assertFalse(self.registry.management.active_devices)

    def test_authentication_and_device_only_listener(self):
        for token in ('','a'*64):self.assertEqual(self.request('POST','/v1/commands/'+DEVICE,b'{}',token)[0],401)
        public=fixture.Server(('127.0.0.1',0),self.registry,fixture.OPERATOR,agent_only=True)
        worker=fixture.threading.Thread(target=public.serve_forever,daemon=True);worker.start()
        try:self.assertEqual(self.request('POST','/v1/commands/'+DEVICE,b'{}',server=public)[0],404)
        finally:public.shutdown();public.server_close();worker.join()
        self.assertFalse(self.writes)

    def test_identical_graph_cannot_change_command_meaning(self):
        modified=copy.deepcopy(self.binding)
        modified['contract']['commands']['get_color']['description']='Different'
        modified['contract']['contract_id']=identity(modified['contract']['commands'],modified['contract']['exposed'])
        with self.assertRaisesRegex(ValueError,'conflict'):
            self.registry.management.accept_release_labels(dict(before=dict(identity=dict(base_sha256='a'*64)),
                plan=dict(services=[dict(name='bridge',version='1',permissions=dict(publish_mask=1)),dict(name='example.shell',version='1',permissions=dict(publish_mask=2))],channels=[],service_commands=[modified]),banks={'0':dict(digest='b'*64)}))


if __name__=='__main__':unittest.main()
