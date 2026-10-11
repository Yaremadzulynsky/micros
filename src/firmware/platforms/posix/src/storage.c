#define _DARWIN_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <micros/storage.h>
#include <micros/platform.h>
#include <micros/capabilities.h>
#include "image.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
#include <limits.h>
#include <fcntl.h>
static char root[PATH_MAX];
static micros_activation_record_t selected;
static unsigned fault;
static int path_for(char *out,size_t size,unsigned bank,unsigned slot,int graph) {
 int n=snprintf(out,size,graph?"%s/b%u.graph":"%s/b%u-s%u.mimg",root,bank,slot);
 return bank<2 && slot<4 && n>0 && (size_t)n<size;
}
static int read_file(const char *path,void *data,size_t bytes) {
 FILE *f=fopen(path,"rb");if(!f)return 0;
 int ok=fread(data,1,bytes,f)==bytes && fgetc(f)==EOF;
 fclose(f);return ok;
}
static int write_file(const char *path,const void *data,size_t bytes) {
 char temporary[PATH_MAX];int n=snprintf(temporary,sizeof(temporary),"%s.new",path);
 if(n<0 || (size_t)n>=sizeof(temporary))return 0;
 FILE *f=fopen(temporary,"wb");if(!f)return 0;
 int ok=fwrite(data,1,bytes,f)==bytes && !fflush(f) && !fsync(fileno(f));
 if(fclose(f))ok=0;
 if(ok)ok=!rename(temporary,path);
 if(ok) {
  int directory=open(root,O_RDONLY);
  ok=directory>=0 && !fsync(directory);
  if(directory>=0)close(directory);
 }
 if(!ok)unlink(temporary);
 return ok;
}
int micros_storage_init(void) {
 const char *directory=getenv("MICROS_CONTROLLER_STORE");
 if(directory) {
  if(strlen(directory)>=sizeof(root))return 0;
  strcpy(root,directory);
  if(mkdir(root,0700) && errno!=EEXIST)return 0;
 } else {
  strcpy(root,"/tmp/micros-controller-XXXXXX");if(!mkdtemp(root))return 0;
 }
 char path[PATH_MAX];int n=snprintf(path,sizeof(path),"%s/selection",root);
 if(n<0 || (size_t)n>=sizeof(path))return 0;
 if(!read_file(path,&selected,sizeof(selected)) || !micros_activation_valid(&selected))selected=micros_activation_empty();
 return 1;
}
int micros_storage_image_path(unsigned bank,unsigned slot,char *out,size_t size) { return path_for(out,size,bank,slot,0); }
uint8_t *micros_storage_read_image(unsigned bank,unsigned slot,size_t *bytes) {
 char path[PATH_MAX];if(!bytes || !path_for(path,sizeof(path),bank,slot,0))return NULL;
 FILE *f=fopen(path,"rb");if(!f)return NULL;
 if(fseek(f,0,SEEK_END)){fclose(f);return NULL;}
 long size=ftell(f);if(size<64 || size>MICROS_BOARD_IMAGE_BYTES){fclose(f);return NULL;}
 rewind(f);uint8_t *data=malloc((size_t)size);
 if(!data || fread(data,1,(size_t)size,f)!=(size_t)size){free(data);fclose(f);return NULL;}
 fclose(f);*bytes=(size_t)size;return data;
}
int micros_storage_write_image(unsigned bank,unsigned slot,const void *data,size_t bytes) {
 char path[PATH_MAX];
 return bank!=selected.good && !selected.pending && bytes>=64 && bytes<=MICROS_BOARD_IMAGE_BYTES &&
  path_for(path,sizeof(path),bank,slot,0) && write_file(path,data,bytes);
}
int micros_storage_read_graph(unsigned bank,micros_device_graph_t *graph) {
 char path[PATH_MAX];return path_for(path,sizeof(path),bank,0,1) && read_file(path,graph,sizeof(*graph));
}
int micros_storage_write_graph(unsigned bank,const micros_device_graph_t *graph) {
 char path[PATH_MAX];return bank!=selected.good && !selected.pending && path_for(path,sizeof(path),bank,0,1) && write_file(path,graph,sizeof(*graph));
}
micros_activation_record_t micros_storage_selection(void) { return selected; }
int micros_storage_select(micros_activation_record_t next) {
 char path[PATH_MAX];int n=snprintf(path,sizeof(path),"%s/selection",root);
 if(n<0 || (size_t)n>=sizeof(path) || !micros_activation_seal(&next,selected.sequence) || !write_file(path,&next,sizeof(next)))return 0;
 selected=next;return 1;
}
int micros_storage_rebind_images(unsigned bank) { return bank<2; }
void micros_storage_fault_arm(unsigned boundary) { fault=boundary; }
void micros_storage_fault_boundary(unsigned boundary) { if(fault && boundary==fault)micros_controller_reset(); }

int micros_storage_prepare(unsigned bank) {
 if(bank>=2 || bank==selected.good || selected.pending)return 0;
 for(unsigned slot=0;slot<4;++slot) {
  char path[PATH_MAX];if(!path_for(path,sizeof(path),bank,slot,0))return 0;
  if(unlink(path) && errno!=ENOENT)return 0;
 }
 char path[PATH_MAX];return path_for(path,sizeof(path),bank,0,1) && (!unlink(path) || errno==ENOENT);
}

int micros_storage_write_image_part(unsigned bank,unsigned slot,size_t offset,const void *data,size_t bytes) {
 char path[PATH_MAX];
 if(bank==selected.good || selected.pending || offset>=MICROS_BOARD_IMAGE_BYTES || bytes>MICROS_BOARD_IMAGE_BYTES-offset || !path_for(path,sizeof(path),bank,slot,0))return 0;
 FILE *f=fopen(path,offset?"r+b":"wb");if(!f)return 0;
 int ok=!fseek(f,(long)offset,SEEK_SET) && fwrite(data,1,bytes,f)==bytes && !fflush(f) && !fsync(fileno(f));
 if(fclose(f))ok=0;
 return ok;
}

int micros_storage_read_image_part(unsigned bank,unsigned slot,size_t offset,void *output,size_t bytes) {
    char path[PATH_MAX];
    if(offset>MICROS_BOARD_IMAGE_BYTES || bytes>MICROS_BOARD_IMAGE_BYTES-offset ||
       !path_for(path,sizeof(path),bank,slot,0))return 0;
    FILE *file=fopen(path,"rb");if(!file)return 0;
    int okay=!fseek(file,(long)offset,SEEK_SET) && fread(output,1,bytes,file)==bytes;
    fclose(file);return okay;
}
