/* Host simulation of mapping lifetime and bank write protection. No CPU/MMU emulation. */
#include "storage.h"
#include "esp_partition.h"
#include "mbedtls/sha256.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static esp_partition_t services = {262144, 0}, activation = {8192, 1};
static uint8_t flash[262144], journal[8192];
static unsigned maps, unmaps, fail_data, mismatch_bank, fail_bank_once;
const esp_partition_t *esp_partition_find_first(int type, int subtype, const char *name)
{ (void)type; (void)subtype; return !strcmp(name,"services") ? &services : &activation; }
int esp_partition_read(const esp_partition_t *p,size_t off,void *out,size_t n)
{ assert(off+n<=p->size); memcpy(out,(p->id ? journal:flash)+off,n); return 0; }
int esp_partition_write(const esp_partition_t *p,size_t off,const void *in,size_t n)
{ assert(off+n<=p->size); memcpy((p->id ? journal:flash)+off,in,n); return 0; }
int esp_partition_erase_range(const esp_partition_t *p,size_t off,size_t n)
{ assert(off+n<=p->size); memset((p->id ? journal:flash)+off,255,n); return 0; }
int esp_partition_mmap(const esp_partition_t *p,size_t off,size_t n,int kind,const void **out,unsigned *handle)
{ assert(p==&services && off+n<=p->size); if(kind==2 && fail_data) return -1;
  if (off == MICROS_STORAGE_BANK_BYTES && fail_bank_once) { fail_bank_once=0; return -1; }
  *out=flash+(off == MICROS_STORAGE_BANK_BYTES && mismatch_bank ? 64 : 0); *handle=++maps; return 0; }
void esp_partition_munmap(unsigned h) { assert(h); ++unmaps; }
void esp_restart(void) { abort(); }
void mbedtls_sha256_init(mbedtls_sha256_context *c) { (void)c; }
void mbedtls_sha256_free(mbedtls_sha256_context *c) { (void)c; }
int mbedtls_sha256_starts(mbedtls_sha256_context *c,int n) { (void)c;(void)n;return 0; }
int mbedtls_sha256_update(mbedtls_sha256_context *c,const void *p,size_t n) { (void)c;(void)p;(void)n;return 0; }
int mbedtls_sha256_finish(mbedtls_sha256_context *c,uint8_t *p) { (void)c;memset(p,0,32);return 0; }
int main(void)
{
    memset(journal,255,sizeof(journal));
    assert(micros_storage_init());
    uint8_t image[64]={0}; micros_device_graph_t graph={0};
    const void *code,*data;
    assert(!micros_storage_map_bank(2,&code,&data));
    assert(micros_storage_map_bank(0,&code,&data));
    assert(maps==2);
    assert(micros_storage_map_bank(0,&code,&data));
    assert(maps==2);
    assert(!micros_storage_map_bank(1,&code,&data));
    assert(!micros_storage_write_image(0,0,image,sizeof(image)));
    assert(!micros_storage_write_graph(0,&graph));
    assert(micros_storage_write_image(1,0,image,sizeof(image)));
    micros_storage_unmap_bank();
    assert(!unmaps && !micros_storage_write_image(0,0,image,sizeof(image)));
    micros_storage_unmap_bank();
    assert(unmaps==2 && micros_storage_write_image(0,0,image,sizeof(image)));
    fail_data=1;
    assert(!micros_storage_map_bank(1,&code,&data));
    assert(unmaps==3); /* Failed second alias must release first alias. */
    assert(micros_storage_write_image(1,0,image,sizeof(image)));
    fail_data=0;
    assert(micros_storage_map_bank(1,&code,&data));
    assert(!micros_storage_write_image(1,0,image,sizeof(image)));
    micros_storage_unmap_bank();
    assert(micros_storage_map_bank(0,&code,&data)); /* Rollback mapping. */
    micros_storage_unmap_bank();
    assert(maps==unmaps);
    assert(micros_storage_map_bank(0,&code,&data));
    assert(micros_storage_map_bank(0,&code,&data));
    fail_bank_once=1;
    assert(micros_storage_switch_bank(1)==0); /* Original aliases restored after allocation failure. */
    mismatch_bank=1;
    assert(micros_storage_switch_bank(1)==0); /* Wrong virtual address never reaches live workers. */
    mismatch_bank=0;
    assert(micros_storage_switch_bank(1)==1);
    assert(!micros_storage_write_image(1,0,image,sizeof(image)));
    micros_storage_unmap_bank();
    assert(!micros_storage_write_image(1,0,image,sizeof(image))); /* Both peer references survived. */
    micros_storage_unmap_bank();
    assert(maps==unmaps);
    assert(micros_storage_map_bank(0,&code,&data));
    fail_data=1;
    assert(micros_storage_switch_bank(1)==-1); /* Neither bank can be mapped: caller must reboot. */
    assert(maps==unmaps);
}
