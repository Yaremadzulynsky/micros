"""Compile the production rollback entry points against controlled journal I/O.

Only hardware reads/writes are substituted. In particular, a confirmed base has
no candidate and no active upload; that state must permit explicit rollback.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def function(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class RollbackGuardsTest(unittest.TestCase):
    def test_confirmed_idle_base_can_rollback_on_both_targets(self):
        for target in ('esp8266', 'samd21'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                base = ROOT / 'src/firmware/platforms' / target
                if target == 'esp8266':
                    record, header, entry = 'micros_boot_record_t', 'record.h', 'embedded_base_ota_rollback'
                    extra = 'static unsigned staging=UINT32_MAX;'
                    reset_extra = 'staging=UINT32_MAX;'
                    additional = 'reset(); staging=0; assert(!rollback()); assert(!writes);'
                else:
                    record, header, entry = 'samd_boot_record_t', 'layout.h', 'embedded_base_ota_rollback'
                    extra, reset_extra = '', 'saved.image_bytes[0]=512; saved.image_bytes[1]=512;'
                    additional = 'reset(); saved.image_bytes[0]=0; assert(!rollback()); assert(!writes);'
                body = function((base / 'src/update.cpp').read_text(), 'bool ' + entry + '(')
                code = f'''#include <cassert>
#include "{base / 'sdk/boot' / header}"
static {record} saved;
static int journal_index=0,writes=0;
static unsigned running=1;
{extra}
static int load({record} &r) {{r=saved;return journal_index;}}
static bool store({record} r,int index) {{assert(index==journal_index);saved=r;++writes;return true;}}
static unsigned running_slot() {{return running;}}
{body}
static bool rollback() {{return {entry}();}}
static void reset() {{saved={{}};saved.good=1;saved.previous=0;saved.candidate=UINT32_MAX;
 saved.attempts=1;journal_index=0;writes=0;running=1;{reset_extra}}}
int main() {{
 reset();assert(rollback());assert(writes==1);assert(saved.good==1);
 assert(saved.candidate==0 && saved.previous==UINT32_MAX && saved.attempts==0);
 assert(!rollback());assert(writes==1);
 reset();saved.candidate=0;assert(!rollback());assert(!writes);
 reset();saved.previous=UINT32_MAX;assert(!rollback());assert(!writes);
 reset();running=0;assert(!rollback());assert(!writes);
 reset();journal_index=-1;assert(!rollback());assert(!writes);
 {additional}
}}
'''
                source = Path(directory) / 'rollback.cpp'
                source.write_text(code)
                executable = Path(directory) / 'rollback'
                subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                str(source), '-o', str(executable)], check=True)
                subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    unittest.main()
