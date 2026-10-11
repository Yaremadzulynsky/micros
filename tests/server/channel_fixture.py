"""Synthetic channel/board fixture. Never contacts hardware."""
from pathlib import Path
import time
ROOT=Path(__file__).resolve().parents[2]
DEVICE='0123456789ab'

def make_device():
    from micros_tooling.config.configuration import load_project
    from micros_tooling.communication.channel_metadata import build
    service=next(s for s in load_project(ROOT/'examples/pin-monitor/micros.toml')['services'] if s['name']=='board.pin-monitor')
    port=build(service)[0]
    return dict(device_id=DEVICE,name='Workbench · simulated preview',online=True,last_seen=time.time(),status=dict(
        platform='esp32',ipc_stream=1,identity=dict(device_id=DEVICE,base_sha256='a'*64),
        activation=dict(sequence=1,good=0,pending=0,good_sha256='b'*64),heap=180000,uptime_us=60000000,
        services=[dict(name='board.network-bridge',state='Running'),dict(name='board.pin-monitor',state='Running')],
        channel_ports=[dict(service='board.pin-monitor',version='1.0.0',port=port,instance=0,max_payload=64)]))
