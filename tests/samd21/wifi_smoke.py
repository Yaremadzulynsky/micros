#!/usr/bin/env python3
"""Hardware-only fallback test; preserve the existing primary secret by SSID."""
import secrets
import time
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.platforms.samd21.transport import SerialRemote

with SerialRemote() as remote:
    status=remote.status()
    assert not status['base_ota']['pending'] and status['network']['profiles_capacity']==2
    saved=remote.request('WIFI_GET')['networks']
    assert len(saved)==1 and not saved[0]['fallback'], 'Test requires one existing primary'
    home=saved[0]['ssid_hex']
    absent=('micros-test-'+secrets.token_hex(6)).encode().hex()
    try:
        remote.request('WIFI_PROFILES '+absent+' - '+home+' keep')
        assert remote.request('WIFI_GET')['networks'][1]['ssid_hex']==home
        # Force an actual reconnect, not the connection retained by NINA.
        remote.request('WIFI_SET '+absent+' -')
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            state=remote.request('WIFI')
            if state['connected'] and state['profile_index']==1:
                break
            time.sleep(.5)
        else:raise AssertionError('Fallback did not connect within 45 seconds')
        print('PASS: unavailable primary fell back to the existing saved network')
        # Duplicate profiles and missing kept credentials must be rejected atomically.
        for command in ('WIFI_PROFILES '+home+' keep '+home+' keep',
                        'WIFI_PROFILES '+home+' keep '+('unknown-'+secrets.token_hex(4)).encode().hex()+' keep'):
            assert remote.request(command,allow_error=True)['result']!=0
            assert remote.request('WIFI_GET')['networks'][1]['ssid_hex']==home
    finally:
        remote.request('WIFI_PROFILES '+home+' keep - -')
        assert remote.request('WIFI_GET')['networks']==saved
        print('Restored original primary; existing connection and password preserved')
