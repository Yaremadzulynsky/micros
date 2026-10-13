"""Read the public layout from an original ESP-IDF partition-table artifact."""
import hashlib
import struct
from micros_tooling.storage.packages import require


def partitions(data):
    require(32 <= len(data) <= 4096 and len(data) % 32 == 0, 'Invalid partition table length')
    result, checked = [], False
    for offset in range(0, len(data), 32):
        entry = data[offset:offset + 32]
        if entry[:2] == b'\xeb\xeb':
            require(entry[2:16] == b'\xff' * 14 and
                    hashlib.md5(data[:offset]).digest() == entry[16:], 'Partition table checksum mismatch')
            checked = True
            require(all(byte == 255 for byte in data[offset + 32:]), 'Data after partition checksum')
            break
        require(entry[:2] == b'\xaa\x50', 'Invalid partition entry')
        _, kind, subtype, address, size, label, flags = struct.unpack('<HBBII16sI', entry)
        name = label.split(b'\0', 1)[0].decode('ascii')
        require(name and all(32 <= ord(c) < 127 for c in name), 'Invalid partition label')
        require(size > 0 and address >= 0x9000 and address + size <= 16 * 1024 * 1024,
                'Partition outside supported flash range')
        result.append(dict(name=name, offset=address, size=size, type=kind, subtype=subtype))
    require(checked and result, 'Missing partition checksum or entries')
    result.sort(key=lambda p: p['offset'])
    require(len({p['name'] for p in result}) == len(result), 'Duplicate partition label')
    require(all(a['offset'] + a['size'] <= b['offset'] for a, b in zip(result, result[1:])),
            'Overlapping partitions')
    return result
