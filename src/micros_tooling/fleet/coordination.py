"""Compile/admit global typed coordination bindings; inspect live router evidence."""
import argparse
import json
from pathlib import Path
from micros_tooling.config.configuration import load_project, read_toml, unit_identity
from micros_tooling.storage.packages import require, digest, canonical_schema
from micros_tooling.fleet.server import RelayRemote


def connection(state):
    config=json.loads((state/'client.json').read_text())
    return RelayRemote(config['url'],state/'servercert.pem',state/'admin.token','',
                       cloudflare_access=config.get('cloudflare_access') is True)


def compile_routes(path, roster):
    path=Path(path).resolve();doc=read_toml(path)
    require(doc.keys()=={'devices','routes'},'Expected devices and routes')
    devices={}
    for alias,entry in doc['devices'].items():
        require(entry.keys()=={'project'},'Device entry needs project')
        project=path.parent/entry['project'];device=unit_identity(project)
        require(device in roster and roster[device]['online'],'Device offline: '+device)
        recipe=load_project(project)
        devices[alias]=(device,recipe,roster[device]['status'])
    routes=[]
    for route in doc['routes']:
        require(route.keys()=={'name','source','target','drop_first'},'Invalid route')
        ends={};contracts=[]
        for side,access in (('source','publish'),('target','subscribe')):
            parts=route[side].split('.')
            require(len(parts)==3 and parts[0] in devices,'Use device.service.port')
            device,recipe,status=devices[parts[0]]
            service=next((s for s in recipe['services'] if s['_interface']['name']==parts[1]),None)
            require(service is not None,'Unknown service')
            port=next((p for p in service['_interface']['ports'] if p['name']==parts[2]),None)
            require(port and port['access']==access and port.get('kind'),'Wrong direction or untyped port')
            schema=digest(canonical_schema(Path(port['schema']).read_bytes()))
            declaration=next(c for c in service['channels'] if c['schema']==parts[2])
            contracts.append((port['kind'],schema,port['max_payload'],declaration['interface'],declaration['major'],declaration['minor']))
            require(status.get('identity',{}).get('abi_revision')==7,'Requires coordination ABI 7')
            ends[side]=dict(device=device,key=port['key'],base=status['identity']['base_sha256'],
                            graph=status['activation']['good_sha256'],sequence=status['activation']['sequence'])
        require(contracts[0]==contracts[1],'Endpoints must have identical kind, schema, interface version and bounds')
        routes.append(dict(name=route['name'],kind=contracts[0][0],schema=contracts[0][1],
                           max_payload=contracts[0][2],drop_first=route['drop_first'],**ends))
    return dict(routes=routes)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['preview','apply','status','clear'])
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--server-state',type=Path,default=Path('.micros/server'))
    args=parser.parse_args();remote=connection(args.server_state)
    if args.operation=='status':
        result=json.loads(remote.raw('GET','/v1/coordination'))
    elif args.operation=='clear':
        result=json.loads(remote.raw('POST','/v1/coordination',b'{"routes":[]}'))
    else:
        roster=json.loads(remote.raw('GET','/v1/devices'))
        # Operator API returns a devices array wrapper.
        if isinstance(roster,dict):roster=roster['devices']
        result=compile_routes(args.project,{d['device_id']:d for d in roster})
        if args.operation=='apply':
            result=json.loads(remote.raw('POST','/v1/coordination',json.dumps(result).encode()))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
