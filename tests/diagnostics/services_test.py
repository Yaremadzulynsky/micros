"""Compile and exercise diagnostic service sources with real generated protobuf APIs."""
from pathlib import Path
import copy
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / "src"))
from micros_tooling.config.configuration import read_toml, generate_service_headers
from micros_tooling.config.composition import toml
from micros_tooling.config.protobuf import RUNTIME, RUNTIME_SOURCES


class DiagnosticServices(unittest.TestCase):
    def exercise(self, recipe_name, alias, test):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            original=ROOT/'examples/diagnostics'/recipe_name
            recipe=read_toml(original)
            for channel in recipe['channels'].values():
                channel['schema']=str((original.parent/channel['schema']).resolve())
            service=recipe['services'][alias]
            source=(original.parent/service['source']).resolve()
            shutil.copytree(source/'src',directory/'src')
            service['source']='.'
            recipe['services']={alias:service}
            project=directory/'micros.toml';project.write_text(toml(recipe))
            generate_service_headers(project)
            binary=directory/'test'
            subprocess.run(['cc','-std=c17','-Wall','-Wextra','-Werror','-UNDEBUG',
                            '-I'+str(ROOT/'src/sdk/abi/include'),'-I'+str(ROOT/'src/sdk/abi/internal'),'-I'+str(RUNTIME),
                            '-I'+str(directory/'src'),str(ROOT/'tests/diagnostics'/test),
                            str(directory/'generated'/f'{alias}_ipc.c'),
                            *map(str,(directory/'generated').glob('*.pb.c')),*map(str,RUNTIME_SOURCES),
                            '-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)

    def test_probe(self): self.exercise('channel-replay.toml','probe','probe_test.c')
    def test_replay(self): self.exercise('channel-replay.toml','replay','replay_test.c')
    def test_recorder(self): self.exercise('signal-recorder.toml','recorder','recorder_test.c')


if __name__=='__main__': unittest.main()
