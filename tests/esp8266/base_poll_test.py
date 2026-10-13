"""Boot trials must not repeatedly mask interrupts while networking connects."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class BasePollTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'), 'host C++ compiler required')
    def test_poll_rate_confirmation_and_fallback(self):
        source = (ROOT / 'src/firmware/platforms/esp8266/src/update.cpp').read_text()
        poll = source[source.index('void embedded_base_ota_poll()'):source.index('#include <micros/update.h>')]
        harness = r'''
#include <cstdint>
#include <cstdlib>
#define MICROS_BOOT_NONE UINT32_MAX
struct micros_boot_record_t { unsigned good, previous, candidate, attempts; };
static uint64_t now;
static int reads, stores, resets;
static bool online;
static uint64_t esp_timer_get_time() { return now; }
static unsigned running_slot() { return 1; }
static int load(micros_boot_record_t &r) { ++reads; r={0,MICROS_BOOT_NONE,1,1}; return 0; }
static bool embedded_network_online() { return online; }
static bool store(micros_boot_record_t r,int i) {
 ++stores; if(i!=0 || r.good!=1 || r.previous!=0 || r.candidate!=MICROS_BOOT_NONE || r.attempts) abort(); return true;
}
static void embedded_reset() { ++resets; }
'''+poll+r'''
int main(int argc,char **argv) {
 if(argc!=2)return 9;
 int scenario=atoi(argv[1]);
 // Simulate the actual 1 ms management loop, including just before a boundary.
 for(now=0;now<10000000;now+=1000)embedded_base_ota_poll();
 if(reads>100 || stores || resets)return 1;
 if(scenario==1) {
  online=true; embedded_base_ota_poll();
  if(stores!=1 || resets)return 2;
  int before=reads;now+=1000000;embedded_base_ota_poll();
  return reads!=before || stores!=1;
 }
 now=179999999;embedded_base_ota_poll();if(resets)return 3;
 now=180100000;embedded_base_ota_poll();
 return stores || resets!=1;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp); (path/'test.cpp').write_text(harness)
            subprocess.run(['c++','-std=c++17','-Wall','-Werror',str(path/'test.cpp'),'-o',str(path/'test')],check=True,capture_output=True)
            for scenario in ('1','2'):
                subprocess.run([str(path/'test'),scenario],check=True)

if __name__=='__main__': unittest.main()
