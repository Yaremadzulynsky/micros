"""Compile the real services, generated protobuf and lifecycle with a deterministic bus/clock."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from micros_tooling.config.service_generation import generate, definition
from micros_tooling.config.configuration import config_artifacts

ROOT = Path(__file__).resolve().parents[1]


class ClimateTest(unittest.TestCase):
    def test_settings_flow_freshness_and_cleanup(self):
        sdk = Path(os.environ['MICROS_SDK'])
        output = ROOT / 'build/tests'
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as directory:
            work = Path(directory)
            compiler = shlex.split(os.environ.get('CC', 'cc'))
            flags = ['-std=c17', '-Wall', '-Wextra', '-Werror', '-UNDEBUG']
            for path in ('src/sdk/abi/include', 'src/sdk/abi/internal', 'src/third_party/nanopb'):
                flags += ['-I' + str(sdk/path)]
            sources, schemas, generated = [], {}, []
            for name, api in [('climate-sensor','climate'), ('fan-controller','fan'), ('status-display','display')]:
                service = ROOT/'services'/name
                target = work/api
                generate(service/'service.toml', target)
                generated.append(target)
                flags += ['-I'+str(target), '-I'+str(service/'src')]
                sources += [(p, api) for p in (service/'src').glob('*.c')]
                sources += [(target/(api+'_ipc.c'), api), (target/(api+'_lifecycle.c'), api)]
                for p in target.glob('*.pb.c'): schemas.setdefault(p.name, p)
            sources += [(p, None) for p in schemas.values()]
            sources += [(sdk/'src/third_party/nanopb'/name, None) for name in ('pb_common.c','pb_encode.c','pb_decode.c')]
            contract = ROOT/'services/climate-sensor/service.toml'
            schema = definition(contract)[1]['config_schema']
            config = config_artifacts('climate', dict(fields=schema), dict(interval_ms=250))[1]
            harness = (ROOT/'tests/flow.c').read_text().replace('CONFIG_BYTES', ','.join(map(str,config)))
            (work/'flow.c').write_text(harness)
            sources.append((work/'flow.c', None))
            objects = []
            for index, (source, api) in enumerate(sources):
                obj = work/f'{index}.o'
                rename = [f'-Dmicros_service_query={api}_query', f'-Dmicros_descriptor={api}_descriptor'] if api else []
                subprocess.run([*compiler,*flags,*rename,'-c',str(source),'-o',str(obj)],check=True,timeout=30)
                objects.append(str(obj))
            binary = work/'flow'
            subprocess.run([*compiler,*objects,'-o',str(binary)],check=True,timeout=30)
            subprocess.run([str(binary)],check=True,timeout=5)

if __name__ == '__main__': unittest.main()
