"""The host bridge observes the shared native controller's trial and fallback."""
from pathlib import Path
import struct
import sys
import tempfile
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'src'))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from micros_tooling.host.activation import stage, boot_runtime, read_record
from micros_tooling.storage.packages import build_package
from micros_tooling.storage.store import Store
from tools.packaging.demo_packages import build_demo, manifest

build=Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);store=Store(root/'store')
    selection=build_demo(build,root/'packages')
    for name in ('publisher','fast','slow'):store.install((root/'packages'/f'{name}.msp').read_bytes())
    store.configure(selection);stage(store)
    runtime=boot_runtime(store,build/'micros-control');runtime.close()
    assert read_record(store)['good']==selection and read_record(store)['candidate'] is None
    image=(build/'fixture_FAIL_START.mimg').read_bytes()
    description=manifest('fault.start','publish',image,b'')
    description['channels']=[];description['schemas']={}
    description['memory']['arena_bytes']=24
    description['capabilities']=dict(handles=2,timers=1,gpio=[0])
    store.install(build_package(description,image,{}));store.configure({'fault.start':'1.0.0'})
    pending=stage(store);assert stage(store)==pending
    runtime=boot_runtime(store,build/'micros-control')
    assert set(runtime.status()['services'])==set(selection)
    runtime.close()
    assert read_record(store)['good']==selection and read_record(store)['candidate'] is None
    log=(store.root/'runtime.log').read_text()
    assert log.count('AUTOBOOT REJECT')==2 and 'ROLLBACK attempts exhausted' in log,log
    # Reconstruct a power loss with two persisted attempts. The C controller
    # must clear the trial before entering any candidate hook again.
    path=store.root/'controller/selection';record=bytearray(path.read_bytes())
    good=struct.unpack_from('<I',record,8)[0]
    struct.pack_into('<III',record,16,1-good,2,1)
    struct.pack_into('<I',record,124,zlib.crc32(record[:124]));path.write_bytes(record)
    before=(store.root/'runtime.log').stat().st_size
    runtime=boot_runtime(store,build/'micros-control');runtime.close()
    after=(store.root/'runtime.log').read_text()[before:]
    assert 'ROLLBACK attempts exhausted' in after and 'AUTOBOOT REJECT' not in after,after
    assert read_record(store)['good']==selection and read_record(store)['candidate'] is None
print('Shared native controller: host confirmation, failed-start fallback and consumed-attempt recovery passed')
