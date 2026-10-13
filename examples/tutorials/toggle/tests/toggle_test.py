"""Compile the actual three services, generated hooks/protobuf and test their flow."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from micros_tooling.config.service_generation import generate, definition
from micros_tooling.config.configuration import config_artifacts, load_project

ROOT = Path(__file__).resolve().parents[1]

class ToggleTest(unittest.TestCase):
    def test_compiled_event_flow_and_cleanup(self):
        sdk = Path(os.environ['MICROS_SDK'])
        output = ROOT/'build/tests'
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as directory:
            work = Path(directory)
            compiler = shlex.split(os.environ.get('CC', 'cc'))
            flags = ['-std=c17', '-Wall', '-Wextra', '-Werror', '-UNDEBUG']
            for path in ('src/sdk/abi/include','src/sdk/abi/internal','src/third_party/nanopb'):
                flags += ['-I'+str(sdk/path)]
            sources, schemas = [], {}
            for api in ('clock','button','led'):
                service = ROOT/'services'/api
                target = work/api
                generate(service, target)
                flags += ['-I'+str(target)]
                sources += [(service/'src/service.c',api), (target/(api+'_ipc.c'),api), (target/(api+'_lifecycle.c'),api)]
                for path in target.glob('*.pb.c'): schemas.setdefault(path.name,path)
            sources += [(p,None) for p in schemas.values()]
            sources += [(sdk/'src/third_party/nanopb'/name,None) for name in ('pb_common.c','pb_encode.c','pb_decode.c')]
            schema = definition(ROOT/'services/clock')[1]['config_schema']
            config = config_artifacts('clock',dict(fields=schema),dict(interval_ms=250))[1]
            (work/'toggle_flow.c').write_text((ROOT/'tests/toggle_flow.c').read_text().replace('CLOCK_CONFIG_BYTES',','.join(map(str,config))))
            sources.append((work/'toggle_flow.c',None))
            objects=[]
            for index,(source,api) in enumerate(sources):
                obj=work/f'{index}.o'
                rename=[f'-Dmicros_service_query={api}_query',f'-Dmicros_descriptor={api}_descriptor'] if api else []
                subprocess.run([*compiler,*flags,*rename,'-c',str(source),'-o',str(obj)],check=True,timeout=30)
                objects.append(str(obj))
            binary=work/'toggle-flow'
            subprocess.run([*compiler,*objects,'-o',str(binary)],check=True,timeout=30)
            subprocess.run([str(binary)],check=True,timeout=10)

    def test_both_unit_graphs_and_bounds(self):
        import shutil
        output=ROOT/'build/tests'
        output.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as directory:
            work=Path(directory)
            shutil.copytree(ROOT/'services',work/'services')
            shutil.copytree(ROOT/'protos',work/'protos')
            (work/'units').mkdir()
            for profile in ('esp32_devkitc_v4','arduino_mkr_wifi_1010','esp8266_4mb'):
                recipes=[]
                for mode in ('clock','button'):
                    unit=work/'units/001122334455.toml'
                    fragment=(ROOT/f'{mode}-unit.toml').read_text()
                    unit.write_text('[unit]\ndevice_id = "001122334455"\n[board]\nprofile = "'+profile+'"\n'+fragment)
                    recipe=load_project(unit)
                    self.assertEqual(len(recipe['services']),2)
                    self.assertEqual({s['name'] for s in recipe['services']},{'tutorial.'+mode,'tutorial.led'})
                    recipes.append(recipe)
                led=[next(s for s in r['services'] if s['name']=='tutorial.led') for r in recipes]
                self.assertEqual(led[0]['sources'],led[1]['sources'])
                self.assertEqual(led[0]['_contract'],led[1]['_contract'])
                unit.write_text(unit.read_text().replace('depth = 4','depth = 1'))
                with self.assertRaises(Exception): load_project(unit)

if __name__ == '__main__': unittest.main()
