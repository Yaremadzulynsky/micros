#!/usr/bin/env python3
"""Reset the real MCU at every activation write boundary; no base flash writes."""
import argparse
import json
from pathlib import Path
import re
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.platforms.esp32.device import Device, prepare
from micros_tooling.storage.packages import build_package, read_package

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port',required=True)
parser.add_argument('--firmware',type=Path,default=Path('build/esp32-runtime/micros_runtime.elf'))
parser.add_argument('--output',type=Path,default=Path('build/m6-hardware'))
args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
paths=[Path('build/device-demo')/(name+'.msp') for name in ('button','logger','led')]


def selection(device):
    lines=device.status()
    line=next(line for line in lines if line.startswith('ACTIVATION '))
    return {key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',line)}


def observe(device, prefix, timeout=20):
    # Failed candidate messages are expected evidence here, not transport errors.
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        line=device.line()
        if line.startswith(prefix): return line
    raise TimeoutError(prefix)


def stage(device,bank,images,graph):
    device.command('STOP','STOPPED OK')
    for slot,image in sorted(images.items()):
        device.command(f'IMAGE {bank} {slot} {len(image)}','READY')
        device.serial.write(image); device.expect('IMAGE OK')
    device.command(f'CONFIG {bank} {len(graph)}','READY')
    device.serial.write(graph); device.expect('CONFIG OK')

results=[]
with (args.output/'transcript.log').open('w') as log:
    device=Device(args.port,log)
    try:
        current=selection(device)
        if current['good'] == 0xffffffff:
            images,graph,_=prepare(paths,args.firmware,0)
            device.upload(images,graph,0)
        for boundary in range(1,13):
            old=selection(device)['good']; candidate=1-old
            images,graph,_=prepare(paths,args.firmware,candidate)
            stage(device,candidate,images,graph)
            device.command(f'FAULT {boundary}','FAULT ARMED')
            if boundary <= 3:
                image=images[0]
                device.command(f'IMAGE {candidate} 0 {len(image)}','READY'); device.serial.write(image)
            elif boundary <= 5:
                device.command(f'CONFIG {candidate} {len(graph)}','READY'); device.serial.write(graph)
            else: device.serial.write(f'BOOT {candidate}\n'.encode())
            observe(device,'FAULT reset')
            observe(device,'AUTOBOOT OK')
            if 9 <= boundary <= 11: observe(device,'HEALTH COMMITTED')
            state=selection(device)
            expected=candidate if boundary >= 9 else old
            assert state['good']==expected and state['pending']==0, (boundary,state)
            results.append(dict(boundary=boundary,old=old,selected=state['good']))
        # Independently linked candidate fails start; two consumed boot attempts
        # must roll back without relying on its stop hook or a network request.
        old=selection(device)['good']; candidate=1-old
        bad=read_package(paths[0].read_bytes())
        bad['manifest']['image_sha256']=__import__('hashlib').sha256(Path('build/device-failure/service.mimg').read_bytes()).hexdigest()
        failed=args.output/'failed-button.msp'
        failed.write_bytes(build_package(bad['manifest'],Path('build/device-failure/service.mimg').read_bytes(),bad['schemas']))
        images,graph,_=prepare([failed,*paths[1:]],args.firmware,candidate)
        stage(device,candidate,images,graph)
        device.serial.write(f'BOOT {candidate}\n'.encode())
        observe(device,'ROLLBACK attempts exhausted',timeout=30)
        observe(device,'AUTOBOOT OK')
        state=selection(device)
        assert state['good']==old and state['pending']==0,state
        results.append(dict(failed_candidate_rollback=True,selected=old))
    finally: device.close()
(args.output/'report.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
