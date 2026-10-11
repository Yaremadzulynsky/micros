"""Slot-linked MKR base images; never replay an uncertain flash mutation."""
import hashlib
import sys
import http.client
from micros_tooling.communication.remote import RemoteRejected
import time
from pathlib import Path
from micros_tooling.platforms.samd21.build import base_info
from micros_tooling.storage.packages import require


def update(remote,firmware,image=None,dry_run=False):
    info=base_info(firmware)
    data=Path(image or Path(firmware).with_suffix('.bin')).read_bytes()
    require(info['base_slot'] in (0,1),'Build the target base with --base-slot 0 or 1')
    require(len(data)==info['flash_bytes'] and hashlib.sha256(data).digest()==info['hash'],
            'BIN does not match the selected ELF')
    before=remote.status();ota=before.get('base_ota',{})
    require(before.get('platform')=='samd21' and ota.get('version')==1 and ota.get('slot_bytes')==81920,'Install the A/B layout over USB first')
    require(not ota['pending'] and ota['slot']!=info['base_slot'],'Build for the inactive base slot')
    require(not before['pending'],'Wait for the service trial to finish')
    if dry_run:return dict(dry_run=True,slot=info['base_slot'],bytes=len(data),capacity=81920)
    network=hasattr(remote,'relay')
    if network:
        remote.relay.request('POST','/v1/base-image/'+info['hash'].hex(),data)
    remote.request(f"BASE_BEGIN {info['base_slot']} {len(data)} {info['hash'].hex()}")
    if network:
        # Accepted asynchronously: the board downloads, verifies and activates.
        # Never replay this command after an uncertain response.
        command='BASE_FETCH '+info['hash'].hex()
        print(f'Base download: {len(data)} bytes over authenticated HTTPS',file=sys.stderr,flush=True)
    else:
        for offset in range(0,len(data),256):
            chunk=data[offset:offset+256]
            chunk+=b'\xff'*(-len(chunk)%64)
            # Duplicate chunks are acknowledged only when flash already matches byte-for-byte.
            for attempt in range(3):
                try:
                    remote.request(f'BASE_WRITE {offset} {chunk.hex()}');break
                except (OSError,TimeoutError,http.client.HTTPException,RemoteRejected) as error:
                    if isinstance(error,RemoteRejected) and error.status not in (502,503,504):raise
                    if attempt==2:raise
                    time.sleep(1)
            if offset%4096==0 or offset+256>=len(data):
                print(f'Base upload: {min(offset+256,len(data))}/{len(data)} bytes',file=sys.stderr,flush=True)
        command='BASE_ACTIVATE'
    try:remote.request(command)
    except (OSError,TimeoutError,http.client.HTTPException,RemoteRejected) as error:
        if isinstance(error,RemoteRejected) and error.status not in (502,504):raise
        # Never resend activation; resolve its outcome using read-only status below.
        pass
    deadline=time.monotonic()+(150 if network else 60)
    while time.monotonic()<deadline:
        time.sleep(2)
        try:status=remote.status()
        except (OSError,ValueError,TimeoutError,RemoteRejected) as error:
            if isinstance(error,RemoteRejected) and error.status not in (502,503,504):raise
            if hasattr(remote,'serial'):
                remote.serial.close()
                try:remote.__init__(None,remote.serial_number)
                except (OSError,ValueError):pass
            continue  # Read-only polling after reboot.
        ota=status.get('base_ota',{})
        if status['base_sha256']==info['hash'].hex() and not ota.get('pending'):
            return dict(confirmed=True,status=status,firmware=str(Path(firmware).resolve()))
        if not ota.get('pending') and ota.get('staging',0xffffffff)>1 and status['base_sha256']==before['base_sha256']:
            raise ValueError('New base did not confirm; previous base restored')
    raise TimeoutError('Base confirmation unknown; inspect status before another update')
