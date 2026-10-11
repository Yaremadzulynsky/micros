"""The ESP8266 SDK's disabled assertions must not remove mutex operations."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class SynchronizationTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'host C compiler required')
    def test_real_lock_functions_execute_with_empty_config_assert(self):
        source = (ROOT / 'src/firmware/platforms/esp8266/src/platform.c').read_text()
        functions = '\n'.join(re.search(r'void micros_platform_' + name + r'\([^\n]+\) \{.*?\n\}', source, re.S)[0] for name in ('lock', 'unlock'))
        harness = '''
#include <stdlib.h>
#define configASSERT(x)
#define pdTRUE 1
#define portMAX_DELAY 999
static int takes, gives;
typedef struct { int mutex; } micros_platform_sync_t;
static int xSemaphoreTake(int mutex,int timeout) { if(mutex!=7 || timeout!=999) abort(); ++takes; return 1; }
static int xSemaphoreGive(int mutex) { if(mutex!=7) abort(); ++gives; return 1; }
static void micros_esp8266_panic(void) { abort(); }
'''+functions+'''
int main(void) { micros_platform_sync_t sync={7}; micros_platform_lock(&sync); micros_platform_unlock(&sync); return !(takes==1 && gives==1); }
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / 'test.c').write_text(harness)
            subprocess.run(['cc','-std=c11','-Wall','-Werror',str(path/'test.c'),'-o',str(path/'test')],check=True,capture_output=True)
            subprocess.run([str(path/'test')],check=True)

if __name__ == '__main__': unittest.main()
