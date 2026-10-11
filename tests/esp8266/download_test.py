"""Run the actual firmware download loop against interrupted HTTP and flash I/O."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class DownloadTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'), 'host C++ compiler required')
    def test_partial_reads_retry_identical_ranges_and_failures_are_bounded(self):
        source = (ROOT / 'src/firmware/platforms/esp8266/src/network.cpp').read_text()
        download = source[source.index('static bool download('):source.index('static void run(')]
        harness = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <algorithm>
struct Settings {};
struct Client { unsigned offset, count, cursor; } client;
static char mac[]="device", fetch_hash[]="hash";
static uint8_t wire[664];
static const char *stage;
static int scenario, opens, writes, duplicates;
static bool interrupted;
static std::vector<uint8_t> flashed;
static uint64_t esp_timer_get_time() { static uint64_t t; return ++t; }
static unsigned embedded_base_ota_size() { return 1536; }
static void disconnect_tls() {}
static void vTaskDelay(unsigned) {}
#define pdMS_TO_TICKS(x) (x)
static Client *open(const Settings &,const char *,int,const char *,bool,bool,const char *range) {
    ++opens;
    if(scenario==2) return NULL;
    unsigned end;
    if(sscanf(range,"bytes=%u-%u",&client.offset,&end)!=2) abort();
    client.count=end-client.offset+1;client.cursor=0;
    if(client.count>1024) abort();
    return &client;
}
static int esp_http_client_fetch_headers(Client *c) { return c->count; }
static int esp_http_client_get_status_code(Client *) { return 206; }
static int esp_http_client_read(Client *c,char *out,unsigned n) {
    if(scenario==1 && c->cursor==256 && !interrupted) {interrupted=true;return -1;}
    n=std::min(n,c->count-c->cursor);
    for(unsigned i=0;i<n;++i)out[i]=(c->offset+c->cursor+i)%251;
    c->cursor+=n;return n;
}
static bool esp_http_client_is_complete_data_received(Client *c) { return c->cursor==c->count; }
static bool embedded_base_ota_write(unsigned offset,const uint8_t *data,unsigned n) {
    ++writes;
    if(scenario==3)return false;
    if(offset>flashed.size())abort();
    n=std::min(n,embedded_base_ota_size()-offset);
    if(offset<flashed.size()) {
        ++duplicates;
        if(offset+n>flashed.size() || memcmp(flashed.data()+offset,data,n))abort();
    } else flashed.insert(flashed.end(),data,data+n);
    return true;
}
'''+download+r'''
int main(int argc,char **argv) {
    if(argc!=2)return 9;
    scenario=atoi(argv[1]);bool ok=download(Settings{});
    if(scenario==1)return !(ok && flashed.size()==1536 && duplicates==1 && opens==3);
    if(scenario==2)return !(!ok && opens==3 && writes==0);
    if(scenario==3)return !(!ok && opens==1 && writes==1);
    return 8;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'test.cpp').write_text(harness)
            subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror',str(root/'test.cpp'),'-o',str(root/'test')],check=True,capture_output=True)
            for scenario in (1,2,3):
                with self.subTest(scenario=scenario):
                    subprocess.run([str(root/'test'),str(scenario)],check=True)

if __name__ == '__main__': unittest.main()
