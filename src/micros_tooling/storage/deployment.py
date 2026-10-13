"""One controller deployment record, independent of storage addresses and CPU ISA."""
import struct
import zlib
from .packages import require

GRAPH_MAGIC = 0x3247524D
GRAPH_VERSION = 1
GRAPH_BYTES = 1456
SERVICE_SLOTS = 4

def encode_graph(plan, bank, slots, bindings=None):
    require(bank in (0, 1), 'Invalid image set')
    services = plan['services']
    channels = plan['channels']
    require(0 < len(services) <= SERVICE_SLOTS and len(channels) <= 4, 'Controller capacity exceeded')
    bindings = bindings or dict(gpio=[], recovery_button=None)
    from micros_tooling.config.resources import validate_bindings
    validate_bindings(bindings, target=plan["target"] if plan["target"] in (2, 5, 6) else 2)
    lines = bindings['gpio']
    records, configurations, used = [], [], set()
    for service in services:
        slot = slots[service['name']]
        require(0 <= slot < SERVICE_SLOTS and slot not in used, 'Conflicting image slot')
        used.add(slot)
        policy, memory = service['permissions'], service['memory']
        require(policy['gpio_mask'] < (1 << len(lines)), 'GPIO grant has no deployment binding')
        records.extend([slot, service['handles'], policy['timers'], policy['gpio_mask'],
                        policy['publish_mask'], policy['subscribe_mask'], memory['arena_bytes'],
                        memory['arena_alignment'], memory['stack_bytes']])
        configuration = bytes.fromhex(service.get('config', ''))
        require(len(configuration) <= 256, 'Configuration exceeds controller capacity')
        configurations.append(struct.pack('<I', len(configuration)) + configuration.ljust(256, b'\0'))
    channel_words = []
    for channel in channels:
        channel_words.extend([channel['key'], 1 if channel['policy'] == 'stream' else 2,
                              channel['depth'], channel['max_payload']])
    words = [GRAPH_MAGIC, GRAPH_VERSION, bank, len(services), len(channels)]
    words += channel_words + [0] * (16 - len(channel_words))
    words += records + [0] * (36 - len(records))
    body = struct.pack('<' + 'I' * len(words), *words)
    body += b''.join(configurations).ljust(1040, b'\0')
    recovery = next((item['line'] for item in lines if item['name'] == bindings['recovery_button']), 0xFFFFFFFF)
    body += struct.pack('<II', len(lines), recovery)
    for item in lines:
        body += struct.pack('<II36s', item['pin'], item['direction'] == 'output', item['name'].encode())
    body += bytes((4 - len(lines)) * 44)
    result = body + struct.pack('<I', zlib.crc32(body))
    require(len(result) == GRAPH_BYTES, 'Internal deployment record size mismatch')
    return result
