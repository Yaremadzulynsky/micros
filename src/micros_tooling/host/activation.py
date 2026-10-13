"""Host package names mapped onto the native controller's durable selection.

The shared C controller owns trials, health confirmation and rollback. These
files retain package names for the CLI; they never select a boot bank.
"""
import struct
import zlib
from micros_tooling.storage.packages import canonical_json, require
from micros_tooling.storage.store import atomic_write

NONE = 0xFFFFFFFF


def native_selection(store):
    path = store.root / 'controller' / 'selection'
    if not path.exists():
        return None
    data = path.read_bytes()
    require(len(data) == 132, 'native activation record size')
    fields = struct.unpack('<7I', data[:28])
    checksum, commit = struct.unpack('<II', data[124:])
    require(fields[0] == 0x3141434D and commit == 0x54494D43 and
            checksum == zlib.crc32(data[:124]), 'native activation record integrity')
    return dict(sequence=fields[1], good=fields[2], previous=fields[3],
                candidate=fields[4], attempts=fields[5], pending=fields[6])


def read_record(store):
    native = native_selection(store)
    request = store.metadata('activation-request.json', None)
    if native is None and request is None:
        return None
    catalog = store.metadata('controller-catalog.json', {'banks': {}})
    def selection(bank):
        return catalog['banks'].get(str(bank), {}).get('selection')
    return dict(format=2, good=selection(native['good']) if native else None,
                previous=selection(native['previous']) if native else None,
                candidate=selection(native['candidate']) if native and native['pending'] else request,
                attempts=native['attempts'] if native else 0)


def stage(store):
    """Queue the desired package selection; native activation owns its outcome."""
    with store.locked():
        selection = store.selection()['enabled']
        store.plan(selection)
        pending = store.metadata('activation-request.json', None)
        require(pending is None or pending == selection, 'another activation request is pending')
        current = read_record(store)
        if not current or current['good'] != selection:
            if pending is None:
                catalog = store.metadata('controller-catalog.json', {'banks': {}})
                catalog.pop('submitted', None)
                atomic_write(store.root / 'controller-catalog.json', canonical_json(catalog))
            atomic_write(store.root / 'activation-request.json', canonical_json(selection))
        return read_record(store)


def boot_runtime(store, executable):
    from micros_tooling.host.native_process import NativeRuntime
    return NativeRuntime(store, executable)
