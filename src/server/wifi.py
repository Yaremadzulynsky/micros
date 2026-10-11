"""Dedicated Wi-Fi secret transport. No console jobs, archives, or payload logging."""
import struct


def encode(payload):
    networks = payload.get('networks')
    if not isinstance(networks, list) or len(networks) != 4:
        raise ValueError('Expected three primary rows and one fallback row')
    records, seen = [], set()
    for network in networks:
        if network is None:
            records.append(bytes(100))
            continue
        if not isinstance(network, dict):
            raise ValueError('Invalid network entry')
        ssid = network.get('ssid')
        password = network.get('password')
        if not isinstance(ssid, str) or '\0' in ssid:
            raise ValueError('SSID must be text without null characters')
        ssid = ssid.encode('utf-8')
        if not 1 <= len(ssid) <= 32 or ssid in seen:
            raise ValueError('Use distinct network names of 1–32 UTF-8 bytes')
        seen.add(ssid)
        if password is None:
            mode, password = 1, b''  # Board looks up the existing secret by exact SSID.
        else:
            if not isinstance(password, str) or '\0' in password:
                raise ValueError('Invalid Wi-Fi password')
            password = password.encode('utf-8')
            if not (len(password) == 0 or 8 <= len(password) <= 63 or
                    len(password) == 64 and all(c in b'0123456789abcdefABCDEF' for c in password)):
                raise ValueError('Password must be 8–63 UTF-8 bytes, or a 64-character hex key')
            mode = 2
        records.append(struct.pack('BBBB32s64s', len(ssid), len(password), mode, 0, ssid, password))
    if not seen:
        raise ValueError('Keep at least one network')
    return b'MWF1' + b''.join(records)


def samd_settings(remote, payload, capacity=1):
    import secrets
    def command(text):
        result = remote.request('POST', '/v1/platform-command',
                                ('@'+secrets.token_hex(16)+' '+text).encode('ascii'))
        if result.get('result') != 0: raise ValueError('Device rejected Wi-Fi settings; reload before retrying')
        return result
    if payload is None:
        result = command('WIFI_GET')
        return dict(networks=[dict(ssid=bytes.fromhex(n['ssid_hex']).decode('utf-8'),
                    fallback=n.get('fallback') is True,secured=n['secured'] is True) for n in result['networks']])
    networks=payload.get('networks')
    if capacity not in (1,2) or not isinstance(networks,list) or len(networks)!=capacity or networks[0] is None:
        raise ValueError('Keep a primary network and use the available fallback row')
    encode(dict(networks=networks+[None]*(4-capacity)))
    fields=[]
    for n in networks:
        if n is None:
            fields.extend(('-', '-'));continue
        password=n.get('password')
        secret='keep' if password is None else password.encode('utf-8').hex() or '-'
        fields.extend((n['ssid'].encode('utf-8').hex(),secret))
    command(('WIFI_PROFILE ' if capacity==1 else 'WIFI_PROFILES ')+' '.join(fields))
    return dict(ok=True)


def settings(remote, payload=None, reported_status=None):
    # Validate before acquiring a device lease, and never retain a failed payload.
    status = reported_status if reported_status and reported_status.get('platform') in ('samd21', 'esp8266') else remote.status()
    if status.get('platform') in ('samd21', 'esp8266'):
        return samd_settings(remote, payload, status.get('network',{}).get('profiles_capacity',1))
    wire = encode(payload) if payload is not None else None
    if status.get('network', {}).get('profiles_api') != 1:
        raise ValueError('This board needs the compatible USB base update before Wi-Fi settings can be edited')
    if wire is None:
        result = remote.request('GET', '/v1/wifi')
        # Whitelist metadata rather than passing arbitrary device fields to the browser.
        return dict(networks=[dict(ssid=bytes.fromhex(n['ssid_hex']).decode('utf-8', errors='strict'),
                                   fallback=n['fallback'] is True, secured=n['secured'] is True)
                              for n in result['networks']])
    with remote.deployment_session(status):
        remote.request('PUT', '/v1/wifi', wire)
    return dict(ok=True)
