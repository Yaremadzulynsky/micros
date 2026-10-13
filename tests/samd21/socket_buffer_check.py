"""Exercise the patched pinned WiFiNINA receive implementation with failed malloc.

Run: python tests/samd21/socket_buffer_check.py PATH_TO_WIFININA
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from micros_tooling.platforms.build_samd21 import patch_nina_socket_buffer
source=Path(sys.argv[1])/'src/utility'
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);(root/'utility').mkdir()
    (root/'socket.cpp').write_text(patch_nina_socket_buffer((source/'WiFiSocketBuffer.cpp').read_text()))
    shutil.copyfile(source/'WiFiSocketBuffer.h',root/'WiFiSocketBuffer.h')
    (root/'utility/wl_definitions.h').write_text('#define WIFI_MAX_SOCK_NUM 4\n')
    (root/'utility/server_drv.h').write_text('#include <stdint.h>\nstruct ServerDrv { static int getDataBuf(int, uint8_t *, uint16_t *); };\n')
    (root/'test.cpp').write_text(r'''
#include <assert.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
static bool fail_alloc=true;
static unsigned calls=0, cursor=0;
static void *test_malloc(size_t size) { assert(size==256); return fail_alloc ? NULL : malloc(size); }
#define malloc test_malloc
#include "socket.cpp"
#undef malloc
int ServerDrv::getDataBuf(int, uint8_t *data, uint16_t *size) {
 assert(data);assert(*size==256);++calls;
 *size=(uint16_t)(cursor < 1000 ? (1000-cursor < *size ? 1000-cursor : *size) : 0);
 for(unsigned i=0;i<*size;i++)data[i]=(uint8_t)(cursor++);
 return *size>0;
}
int main() {
 uint8_t data[1000];
 assert(WiFiSocketBuffer.available(0)==0 && calls==0);
 assert(WiFiSocketBuffer.read(0,data,sizeof(data))==0 && calls==0);
 fail_alloc=false;unsigned count=0;
 while(count<sizeof(data)) {
  int n=WiFiSocketBuffer.read(0,data+count,73);
  assert(n>0);count+=n;
 }
 for(unsigned i=0;i<count;i++)assert(data[i]==(uint8_t)i);
 assert(calls==4);WiFiSocketBuffer.close(0);
 fail_alloc=true;assert(WiFiSocketBuffer.available(0)==0 && calls==4);
}
''')
    subprocess.run(['c++','-std=c++17','-fsanitize=address','-I'+str(root),str(root/'test.cpp'),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],check=True)
print('WiFiNINA allocation failure, chunked reads and cleanup passed')
