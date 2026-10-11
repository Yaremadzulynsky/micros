#!/usr/bin/env python3
"""Compile bounded schemas, build a native Nanopb codec, and run contract tests."""
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.protobuf import compile_schema, RUNTIME, RUNTIME_SOURCES
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


def main():
    pool = descriptor_pool.DescriptorPool()
    with tempfile.TemporaryDirectory(prefix='micros-coordination-') as temporary:
        output = Path(temporary)
        for schema in sorted(HERE.glob('*.proto')):
            contract = compile_schema(schema)
            descriptions = descriptor_pb2.FileDescriptorSet.FromString(contract['descriptor'])
            for description in descriptions.file:
                try:
                    pool.FindFileByName(description.name)
                except KeyError:
                    pool.Add(description)
            module = types.ModuleType(schema.stem + '_pb2')
            description = pool.FindFileByName(schema.name)
            for name, message in description.message_types_by_name.items():
                setattr(module, name, message_factory.GetMessageClass(message))
            sys.modules[module.__name__] = module
            for filename, content in contract['files'].items():
                (output / filename).write_text(content)
            print(f'{schema.name}: bounded Nanopb maximum {contract["maximum"]} bytes', flush=True)
            if schema.stem == 'wire':
                assert contract['maximum'] <= 192
        codec = output / 'codec'
        subprocess.run(['cc', '-std=c17', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(output), '-I' + str(RUNTIME),
                        str(HERE / 'codec.c'), *map(str, output.glob('*.pb.c')),
                        *map(str, RUNTIME_SOURCES), '-o', str(codec)], check=True)
        import contract_test
        contract_test.CODEC = str(codec)
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromModule(contract_test))
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
