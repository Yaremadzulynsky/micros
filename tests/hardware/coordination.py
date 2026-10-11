"""Read-only proof collector for the deployed two-board coordination demo."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / "src"))
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from micros_tooling.config.protobuf import compile_schema
from micros_tooling.fleet.coordination import connection
from micros_tooling.storage.packages import require


def decoder(path):
    contract=compile_schema(path)
    descriptors=descriptor_pb2.FileDescriptorSet.FromString(contract['descriptor'])
    pool=descriptor_pool.DescriptorPool()
    for file in descriptors.file:pool.Add(file)
    description=pool.FindFileByName(Path(path).name)
    return message_factory.GetMessageClass(next(iter(description.message_types_by_name.values())))


def current_completion(status):
    """Ignore retained history and loss counters from earlier route admissions."""
    routes = {route['name']: route for route in status['routes']}
    if not {'ir.target', 'ir.operation'} <= routes.keys():
        return None
    state, action = routes['ir.target'], routes['ir.operation']
    if any(route['blocked'] or set(route['bound']) != {'source', 'target'}
           for route in (state, action)):
        return None
    if (state['drops'].get('target', 0) < 3 or
        action['drops'].get('target', 0) < 3 or
        action['drops'].get('source', 0) < 3):
        return None
    matches = [event for event in status['events']
               if event.get('route') == 'ir.operation' and
               event.get('side') == 'target' and event.get('status') == 2 and
               action['epoch'] and event.get('generation') == action['epoch']]
    return matches[-1] if matches else None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('build/coordination/proof.json'))
    parser.add_argument('--timeout',type=int,default=120)
    args=parser.parse_args();remote=connection(Path('.micros/server'))
    action=decoder('src/sdk/protos/coordination/v1/ir_action.proto')
    deadline=time.monotonic()+args.timeout
    while True:
        status=json.loads(remote.raw('GET','/v1/coordination'))
        require(status['routes'] and not any(r['blocked'] for r in status['routes']), 'Route absent or fenced: '+json.dumps(status['routes']))
        completion = current_completion(status)
        if completion:
            result=action.FromString(bytes.fromhex(completion['payload']))
            require((result.code,result.transmissions,result.optical_matches,result.applied_value)==
                    (0xbb44ff00,1,1,73),'Physical result differs from expected evidence')
            evidence=dict(router=status,physical_result=dict(code=hex(result.code),
                transmissions=result.transmissions,optical_matches=result.optical_matches,applied_value=result.applied_value),
                captured_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(evidence,indent=2)+'\n')
            print('PASS: state 73, exactly one TX and matching optical RX, nine or more dropped advertisements')
            return
        require(time.monotonic()<deadline,'No physical completion before deadline')
        time.sleep(2)

if __name__=='__main__':main()
