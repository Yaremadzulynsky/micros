"""Isolated design/interaction fixture. All devices and responses are synthetic.

Run: build/python/bin/python tests/server/console_design_fixture.py
No credentials, real device connections, or persistent mutations.
"""
import copy
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit, parse_qs
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from channel_fixture import make_device, ROOT, DEVICE


def make_fleet():
    board=make_device()
    board.update(name='Workbench',last_seen=time.time())
    status=board['status']
    status.update(uptime_us=13932000000, reset_reason=1, labels_source='verified_release',
        identity=dict(device_id=DEVICE,base_sha256='a'*64,abi_major=0,abi_revision=6,slots=4,code_bytes=16384,data_bytes=16384),
        board=dict(profile='ESP32 · development board',flash_mb=4,recovery_pin=0,gpio=[dict(name='analog',pin=34,line=0,output=False,level=0),dict(name='indicator',pin=2,line=1,output=True,level=1)]),
        memory=dict(internal_total=280000,internal_free=180000,internal_min=164000,internal_largest=135000,psram_total=0,psram_free=0),
        heap_accounting=dict(ipc_storage=8448,ipc_payload_capacity=8192,ipc_assigned=128,runtime_metadata=6000,supervisor_stack=4096),
        network=dict(connected=True,ip='192.0.2.10',rssi_dbm=-52,disconnects=0,last_disconnect_reason=0,profiles_api=1),
        channels=[dict(key=1,name='samples',policy=1,depth=16,backlog=1,published=13820,missed=0,age_us=20000,payload_bytes=64,retained_bytes=64)])
    for i,service in enumerate(status['services']):
        service.update(version='1.0.0',arena_reserved=2048,stack_reserved=4096,stack_free_bytes=3072,timers_open=1,timers_limit=2,handles_open=2,handles_limit=4,gpio_granted=1 if i else 0,gpio_open=1 if i else 0,publish_mask=1 if i else 0,subscribe_mask=0 if i else 1,result=0,steps=18302,callbacks=800,hook_max_us=72,callback_max_us=34,timer_late_max_us=21)
    status['flash']=dict(total_bytes=4194304,partitions=[dict(name='nvs',offset=36864,size=24576),dict(name='ota_0',offset=65536,size=1572864),dict(name='ota_1',offset=1638400,size=1572864),dict(name='services',offset=3211264,size=262144)],services=dict(slot_bytes=16384,slots=[dict(slot=i,name=s['name'],offset=4096+i*16384,reserved_bytes=16384,image_bytes=6000+i*2700) for i,s in enumerate(status['services'])]))
    offline=copy.deepcopy(board);offline.update(device_id='0123456789ac',name='Sensor node',online=False,last_seen=time.time()-7200);offline['status']['platform']='esp8266';offline['status']['board']['profile']='ESP8266 · sensor board'
    empty=copy.deepcopy(board);empty.update(device_id='0123456789ad',name='New board');empty['status'].update(services=[],channel_ports=[],channels=[],activation={'good':4294967295,'pending':False})
    return [board,offline,empty]


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wifi-fail-once',action='store_true')
    parser.add_argument('--unnamed',action='store_true')
    parser.add_argument('--empty',action='store_true',help='Show first use with no enrolled boards')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--remote-flows',action='store_true',help='Illustrative incoming and outgoing remote routes')
    args=parser.parse_args()
    fleet=make_fleet();jobs={};events=[];counter=0;wifi_failures=int(args.wifi_fail_once)
    if args.remote_flows:
        status=fleet[0]['status']
        status['channels']=[dict(key=1,name='ir.actions',policy=2),dict(key=2,name='coord.target',policy=2),dict(key=3,name='ir.frames',policy=1),dict(key=4,name='pin.samples',policy=1)]
        prototype=status['services'][0]
        status['services']=[dict(prototype,name=name,publish_mask=p,subscribe_mask=s) for name,p,s in (
            ('board.console',0,4),('board.network-bridge',0,12),('board.ir-coordination',4,3),('board.pin-monitor',8,0))]
        status['remote_connections']=[dict(key=key,direction=direction,peer_device=device,peer_name=name,
            route=route,state=state,reason='Synthetic preview route') for key,direction,device,name,route,state in (
            (1,'publish','111111111111','Control board','ir.operation','Ready'),
            (2,'publish','111111111111','Control board','ir.target','Ready'),
            (3,'subscribe','222222222222','Monitor board','ir.frames','Offline'))]
        controller=copy.deepcopy(fleet[0]);controller.update(device_id='111111111111',name='Control board')
        controller['status']['services']=[dict(prototype,name='coordination.controller',publish_mask=3,subscribe_mask=0)]
        controller['status']['channels']=copy.deepcopy(status['channels'][:2])
        controller['status']['remote_connections']=[dict(c,direction='subscribe',peer_device=DEVICE,peer_name='Workbench') for c in status['remote_connections'][:2]]
        monitor=copy.deepcopy(fleet[1]);monitor.update(device_id='222222222222',name='Monitor board')
        monitor['status']['services']=[dict(prototype,name='board.console',publish_mask=0,subscribe_mask=4)]
        monitor['status']['channels']=[copy.deepcopy(status['channels'][2])]
        monitor['status']['remote_connections']=[dict(status['remote_connections'][2],direction='publish',peer_device=DEVICE,peer_name='Workbench')]
        fleet.extend([controller,monitor])
    if args.unnamed:
        fleet[0]['status'].pop('labels_source',None)
        for service in fleet[0]['status']['services']:
            service.pop('name',None);service.pop('version',None)
    if args.empty: fleet=[]
    networks=[dict(ssid='Lab network',fallback=False,secured=True)]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send(self,data,code=200,mime='application/json'):
            raw=json.dumps(data).encode() if mime=='application/json' else data
            self.send_response(code);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            global wifi_failures
            route=urlsplit(self.path).path
            if route=='/console/api/devices':
                for d in fleet:
                    if d['online']:d['last_seen']=time.time()
                return self.send(dict(devices=fleet))
            if route.endswith('/history'):return self.send(dict(samples=[dict(time=time.time()-i*30,heap=180000+(i%7)*500,rssi_dbm=-52-i%5) for i in range(90,-1,-1)],events=events or [dict(time=time.time()-1800,action='Application deployed',outcome='complete',detail='Synthetic preview: pin monitor and network bridge are running.')]))
            if '/jobs/' in route:return self.send(jobs[route.rsplit('/',1)[1]])
            if route.endswith('/wifi'):
                if wifi_failures:
                    wifi_failures-=1;return self.send(dict(error='Synthetic connection interrupted. Try again.'),503)
                return self.send(dict(networks=networks))
            if route.endswith('/status'):
                device=next((d for d in fleet if '/'+d['device_id']+'/' in route),None)
                return self.send(device['status'] if device else dict(error='Preview device missing'),200 if device else 404)
            if route.endswith('/logs'):return self.send(dict(boot_id='preview-boot',lost=0,data_hex=b'[preview] monitor: GPIO 34 sampled\n[preview] bridge: samples published\n'.hex(),next=100))
            name='index.html' if route in ('/','/console/') else route.removeprefix('/console/')
            if name not in ('index.html','sankey.min.js','service-graph.js','app.js','wifi.js','flash.js','memory.js','insights.js','style.css','micros-logo.png','workbench-board.png'):return self.send(dict(error='Unknown preview route'),404)
            mime='text/javascript' if name.endswith('.js') else 'text/css' if name.endswith('.css') else 'image/png' if name.endswith('.png') else 'text/html'
            raw=(ROOT/'src/server/web'/name).read_bytes()
            if name=='index.html':raw=raw.replace(b'Management console</span>',b'Design preview &middot; example devices</span>').replace(b'<title>micros',b'<title>Preview &middot; micros').replace(b'<main>',b'<main><p class="caption">Design preview &middot; example devices and connections</p>')
            return self.send(raw,mime=mime)
        def do_POST(self):
            global counter,networks
            payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or '{}')
            route=urlsplit(self.path).path
            if route.endswith('/enroll'):return self.send(dict(token=payload['token'],certificate='SYNTHETIC PREVIEW CERTIFICATE'))
            device=next((d for d in fleet if '/'+d['device_id']+'/' in route),None)
            if device is None:return self.send(dict(error='Preview device missing'),404)
            if route.endswith('/status'):return self.send(device['status'])
            if route.endswith('/rename'):device['name']=payload['name'];return self.send(dict(ok=True))
            if route.endswith('/revoke'):device['online']=False;return self.send(dict(ok=True))
            if route.endswith('/wifi'):
                networks=[dict(ssid=n['ssid'],fallback=i==3,secured=n['password']!='') for i,n in enumerate(payload['networks']) if n];return self.send(dict(ok=True))
            if route.endswith('/action'):
                action=payload['action'];result=dict(message='Preview only: '+action+' completed. No board was contacted.')
                if action in ('pause','recover'):
                    for s in device['status']['services']:s['state']='Stopped' if action=='pause' else 'Running'
                if action=='preview':result.update(fingerprint='preview-fingerprint',unchanged=False,plan=dict(services=[dict(name=s['name'],version=s['version'],memory=dict(arena_bytes=2048,stack_bytes=4096)) for s in device['status']['services']],channels=device['status']['channels'],resources=dict(image_bytes=14700)))
                key=str(len(jobs)+1);jobs[key]=dict(state='complete',result=result,progress=[])
                events.insert(0,dict(time=time.time(),action=action,outcome='complete',detail='Synthetic preview operation; no device contacted.'))
                return self.send(dict(job=key))
            return self.send(dict(error='Unknown synthetic operation'),404)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Synthetic console design preview: http://127.0.0.1:{server.server_port}/console/',flush=True)
    server.serve_forever()
