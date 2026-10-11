"""Prepare or execute one bounded replay using the deployed replay-source service."""
import argparse
import base64
import json
import os
from pathlib import Path
import time

from google.protobuf import descriptor_pb2, json_format
from micros_tooling.config.configuration import load_project
from micros_tooling.config.protobuf import compile_schema
from micros_tooling.communication.protobuf import message_class
from micros_tooling.communication.channels import Channels
from micros_tooling.diagnostics.collect import ROOT, connect_device, open_stream, stream
from micros_tooling.storage.packages import require, canonical_schema, digest
from micros_tooling.storage.workspace import Workspace


def schema_class(path):
    compiled = compile_schema(path)
    descriptors = descriptor_pb2.FileDescriptorSet.FromString(compiled['descriptor'])
    descriptor = next(d for d in descriptors.file if d.name == Path(path).name)
    descriptor.ClearField('dependency') # nanopb bounds are compiler metadata, not imported wire types.
    return message_class(base64.b64encode(descriptor.SerializeToString()).decode())


def prepare(project, script):
    recipe = load_project(project)
    replay = next((s for s in recipe['services'] if s.get('_interface', {}).get('name') == 'replay'), None)
    require(replay is not None and replay['name'] == 'diagnostic.replay-source', 'Recipe must select replay-source with alias replay')
    output = next(p for p in replay['_interface']['ports'] if p['name'] == 'output' and p['access'] == 'publish')
    require(not output.get('kind'), 'Replay requires an ordinary channel publication')
    require(isinstance(script, dict) and script.keys() == {'run_id','frames'}, 'Script requires run_id and frames')
    require(type(script['run_id']) is int and 1 <= script['run_id'] <= 0xffffffff, 'run_id must be a nonzero uint32')
    require(isinstance(script['frames'], list) and 1 <= len(script['frames']) <= 16, 'Replay needs 1..16 frames')
    cls = schema_class(output['schema'])
    command_cls = schema_class(ROOT / 'src/sdk/protos/diagnostics/v1/replay_command.proto')
    schema_hash = digest(canonical_schema(Path(output['schema']).read_bytes()))
    config = replay['_configuration']
    maximum = config['values'].get('max_duration_ms', config['definition']['fields']['max_duration_ms']['default'])
    commands, previous = [], 0
    for index, frame in enumerate(script['frames']):
        require(isinstance(frame,dict) and frame.keys() == {'after_ms','message'}, 'Frame requires after_ms and message')
        offset = frame['after_ms']
        require(type(offset) is int and previous <= offset <= maximum, 'Frame offsets must be ordered and within max_duration_ms')
        require(isinstance(frame['message'],dict), 'Message must be a protobuf JSON object')
        payload = json_format.ParseDict(frame['message'], cls()).SerializeToString(deterministic=True)
        require(len(payload) <= 48, 'Replay frame exceeds the 48-byte payload limit')
        command = command_cls(run_id=script['run_id'], operation=1,index=index,after_ms=offset,
                              payload=payload,schema_sha256=bytes.fromhex(schema_hash))
        commands.append(command.SerializeToString(deterministic=True).hex())
        previous = offset
    start = command_cls(run_id=script['run_id'],operation=2,count=len(commands),schema_sha256=bytes.fromhex(schema_hash))
    return dict(run_id=script['run_id'],schema_sha256=schema_hash,loads=commands,
                start=start.SerializeToString(deterministic=True).hex(),count=len(commands),duration_ms=previous)


def run(remote, project, plan, output, *, timeout=90, clock=time.monotonic):
    require(0 < timeout <= 600, 'Replay timeout must be 0..600 seconds')
    channels = Channels(remote, project)
    require('replay' in channels.ports, 'Bridge needs a publication named replay bound to replay.commands')
    target = Path(output)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x') as evidence:
        opened = None
        try:
            opened, provenance = open_stream(remote,'diagnostic.replay-source','status')
            evidence.write(json.dumps(dict(kind='provenance',**provenance,plan=plan))+'\n')
            cursor = opened['cursor']
            deadline = clock()+timeout
            def wait_for(predicate):
                nonlocal cursor
                while clock()<deadline:
                    response=stream(remote,dict(action='read',reader=opened['reader'],cursor=cursor))
                    cursor=response['cursor']
                    for event in response['events']:
                        evidence.write(json.dumps(dict(kind='event',**event))+'\n');evidence.flush()
                        if event.get('state')!='sample': continue
                        status=event['sample']
                        identity=int(status.get('run_id',0))
                        require(identity in (0,plan['run_id']), 'Replay already belongs to another run; do not overwrite it')
                        require(int(status.get('phase',0))!=4, 'Replay failed; inspect retained evidence and runtime status')
                        if identity==plan['run_id']:
                            require(not int(status.get('rejected_commands',0)), 'Replay rejected a command; inspect evidence')
                            if predicate(status): return status
                raise TimeoutError('Replay outcome unconfirmed; inspect status before any retry or restart')
            for index, wire in enumerate(plan['loads']):
                # LOAD is idempotent, but uncertain transport outcomes are never automatically retried.
                channels.write('replay',bytes.fromhex(wire))
                wait_for(lambda s: int(s['loaded_mask']) & (1<<index))
            channels.write('replay',bytes.fromhex(plan['start']))
            result=wait_for(lambda s: int(s['phase'])==3)
            require(int(result['published']) == plan['count'], 'Replay completed with an unexpected publication count')
            evidence.write(json.dumps(dict(kind='replay_end',outcome='completed',published=int(result['published'])))+'\n')
            return result
        except BaseException:
            evidence.write(json.dumps(dict(kind='replay_end',outcome='unconfirmed'))+'\n')
            raise
        finally:
            if opened:
                try: stream(remote,dict(action='close',reader=opened['reader']))
                except Exception: evidence.write(json.dumps(dict(kind='cleanup',lease_closed=False,expires_after_seconds=30))+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True,help='Exact deployed recipe, with replay and bridge aliases')
    parser.add_argument('--script',type=Path,required=True)
    parser.add_argument('--device',help='Omit to prepare/review only; providing a device runs the replay')
    parser.add_argument('--output',type=Path,help='New evidence file, required to run')
    parser.add_argument('--timeout',type=float,default=90)
    args=parser.parse_args()
    require(args.script.stat().st_size<=65536,'Replay script exceeds 64 KiB')
    plan=prepare(args.project,json.loads(args.script.read_text()))
    if not args.device:
        print(json.dumps(plan,indent=2));return
    require(args.output is not None,'--output is required to run')
    remote=connect_device(Workspace(Path(os.environ.get('MICROS_STATE_DIR',ROOT/'.micros'))),args.device)
    print(json.dumps(run(remote,args.project,plan,args.output,timeout=args.timeout)))


if __name__=='__main__': main()
