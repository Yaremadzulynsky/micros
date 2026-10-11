#include <stddef.h>
typedef unsigned nvs_handle_t;
#define NVS_READONLY 0
#define NVS_READWRITE 1
int nvs_open(const char *ns, int mode, nvs_handle_t *h);
int nvs_get_blob(nvs_handle_t h,const char *key,void *v,size_t *n);
int nvs_set_blob(nvs_handle_t h,const char *key,const void *v,size_t n);
int nvs_commit(nvs_handle_t h);
void nvs_close(nvs_handle_t h);
