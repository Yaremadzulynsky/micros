"""Evidence preservation, bounded replay plans, transport uncertainty and operator stream auth."""
import copy
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / "src"))
from micros_tooling.diagnostics import collect, replay
from micros_tooling.storage.packages import PackageError
from server.relay import Registry, Server

PROJECT=ROOT/'examples/diagnostics/channel-replay.toml'
SCRIPT=json.loads((ROOT/'examples/diagnostics/replay.json').read_text())


class DiagnosticClients(unittest.TestCase):
    def test_device_names_resolve_against_live_roster(self):
        remote=Mock()
        remote.raw.return_value=json.dumps({'devices':[{'device_id':'e89f6d30e1a8','name':'feather','online':True,'last_seen':1}]})
        with patch.object(collect,'configured_remote',return_value=remote):
            self.assertIs(collect.connect_device(Mock(),'feather'),remote)
            self.assertEqual(remote.device_id,'e89f6d30e1a8')
            self.assertIs(collect.connect_device(Mock(),'e89f6d30e1a8'),remote)
            with self.assertRaises(PackageError):collect.connect_device(Mock(),'unknown')

    def test_plan_uses_real_schema_and_preserves_values(self):
        plan=replay.prepare(PROJECT,SCRIPT)
        command=replay.schema_class(ROOT/'src/sdk/protos/diagnostics/v1/replay_command.proto')
        output=replay.schema_class(ROOT/'src/sdk/protos/pin/v1/pin_sample.proto')
        frame=command.FromString(bytes.fromhex(plan['loads'][1]))
        self.assertEqual(output.FromString(frame.payload).value,1)
        self.assertEqual(frame.schema_sha256.hex(),plan['schema_sha256'])
        self.assertEqual(frame.after_ms,100)
        # Worst-case valid frame fits the existing platform-command transport.
        frame.run_id=0xffffffff;frame.index=15;frame.after_ms=60000;frame.payload=b'x'*48
        self.assertLessEqual(len('IPC WRITE 3 32 '+frame.SerializeToString().hex()),255)
        self.assertEqual(command.FromString(bytes.fromhex(plan['start'])).count,3)

    def test_rejects_unsafe_or_ambiguous_plans_before_connecting(self):
        for mutate in (lambda s:s.update(run_id=0),lambda s:s.update(frames=[]),
                       lambda s:s.update(frames=s['frames']*6),
                       lambda s:s['frames'][1].update(after_ms=-1),
                       lambda s:s['frames'][1].update(after_ms=70000),
                       lambda s:s['frames'][0]['message'].update(unknown=1)):
            script=copy.deepcopy(SCRIPT);mutate(script)
            with self.assertRaises(Exception): replay.prepare(PROJECT,script)
        with tempfile.TemporaryDirectory() as tmp:
            schema=Path(tmp)/'large.proto'
            schema.write_text('syntax="proto3"; import "nanopb.proto"; message Large { bytes data=1 [(nanopb).max_size=100]; }')
            from micros_tooling.config.configuration import read_toml
            from micros_tooling.config.composition import toml
            doc=read_toml(PROJECT)
            for s in doc['services'].values():s['source']=str((PROJECT.parent/s['source']).resolve())
            for c in doc['channels'].values():c['schema']=str((PROJECT.parent/c['schema']).resolve())
            doc['channels']['samples'].update(schema=str(schema),max_payload=128)
            project=Path(tmp)/'micros.toml';project.write_text(toml(doc))
            import base64
            script={'run_id':1,'frames':[{'after_ms':0,'message':{'data':base64.b64encode(b'a'*60).decode()}}]}
            with self.assertRaisesRegex(PackageError,'48-byte'):replay.prepare(project,script)

    def test_collect_keeps_loss_and_closes_lease_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'capture.jsonl'
            opened=({'reader':'lease','cursor':0},{'device_id':'fixture'})
            with patch.object(collect,'open_stream',return_value=opened) as op,patch.object(collect,'stream') as call:
                call.return_value={'cursor':3,'events':[{'state':'sample','sample':{'value':0}}, {'state':'gap','source':'device','missed':2},{'state':'sample','sample':{'value':1}}]}
                result=collect.collect(Mock(),'probe','report',output,seconds=1,max_events=2,clock=iter([0,0,2]).__next__)
                self.assertEqual(result['samples'],1);self.assertEqual(result['gap_events'],1)
                self.assertEqual(call.call_args.args[1],{'action':'close','reader':'lease'})
                before=output.read_bytes()
                with self.assertRaises(FileExistsError):collect.collect(Mock(),'probe','report',output)
                self.assertEqual(output.read_bytes(),before);self.assertEqual(op.call_count,1)
                self.assertEqual(json.loads(output.read_text().splitlines()[-1])['outcome'],'event_limit')

    def test_capture_failure_retains_partial_evidence_and_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'capture.jsonl'
            with patch.object(collect,'open_stream',return_value=({'reader':'lease','cursor':0},{})),patch.object(collect,'stream',side_effect=[ValueError('application changed'),{}]) as call:
                with self.assertRaisesRegex(ValueError,'application changed'):
                    collect.collect(Mock(),'probe','report',output,clock=lambda:0)
                self.assertIn('interrupted',output.read_text());self.assertEqual(call.call_count,2)

    def test_replay_waits_for_loads_and_never_retries_uncertain_write(self):
        plan=replay.prepare(PROJECT,SCRIPT)
        cls=replay.schema_class(ROOT/'src/sdk/protos/diagnostics/v1/replay_command.proto')
        pending=[];mask=0;writes=[]
        def write(port,wire):
            nonlocal mask
            c=cls.FromString(wire);writes.append(c.operation)
            if c.operation==1:mask|=1<<c.index
            else:self.assertEqual(mask,7)
            pending.append({'state':'sample','sample':{'run_id':1,'phase':1 if c.operation==1 else 3,'loaded_mask':mask,'published':0 if c.operation==1 else 3,'rejected_commands':0}})
        def stream(remote,request):
            if request['action']=='close':return {}
            events=list(pending);pending.clear();return {'cursor':len(writes),'events':events}
        channel=Mock();channel.ports={'replay':{}};channel.write.side_effect=write
        with tempfile.TemporaryDirectory() as tmp,patch.object(replay,'Channels',return_value=channel),patch.object(replay,'open_stream',return_value=({'reader':'lease','cursor':0},{})),patch.object(replay,'stream',side_effect=stream):
            result=replay.run(Mock(),PROJECT,plan,Path(tmp)/'run.jsonl',clock=lambda:0)
            self.assertEqual(result['published'],3);self.assertEqual(writes,[1,1,1,2])
            channel.write.reset_mock();channel.write.side_effect=TimeoutError('uncertain')
            with self.assertRaises(TimeoutError):replay.run(Mock(),PROJECT,plan,Path(tmp)/'uncertain.jsonl')
            self.assertEqual(channel.write.call_count,1);self.assertIn('unconfirmed',(Path(tmp)/'uncertain.jsonl').read_text())

    def test_operator_stream_route_reuses_hub_and_checks_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry=Registry(tmp);server=Server(('127.0.0.1',0),registry,'a'*64)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with patch('server.channel_streams.stream_operation',return_value={'reader':'lease','cursor':0}) as operation:
                    def request(token):
                        c=http.client.HTTPConnection(*server.server_address,timeout=2)
                        c.request('POST','/v1/streams/0123456789ab',json.dumps({'action':'open'}),headers={'Authorization':'Bearer '+token})
                        r=c.getresponse();body=r.read();c.close();return r.status,body
                    self.assertEqual(request('wrong')[0],401);operation.assert_not_called()
                    self.assertEqual(request('a'*64)[0],200)
                    self.assertEqual(operation.call_args.args[1],'0123456789ab')
                    server.agent_only=True
                    self.assertEqual(request('a'*64)[0],404)
                    self.assertEqual(operation.call_count,1)
            finally:server.shutdown();server.server_close();thread.join();registry.db.close()


if __name__=='__main__':unittest.main()
