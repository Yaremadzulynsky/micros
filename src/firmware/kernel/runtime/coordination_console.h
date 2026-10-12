#ifndef MICROS_COORDINATION_CONSOLE_H
#define MICROS_COORDINATION_CONSOLE_H
#include <stdio.h>
#include <string.h>
#include "runtime.h"
#include "../support/integer.h"
/* Caller authenticates transport and excludes graph/base transitions. */
static void micros_coord_console(micros_runtime_t *owner,const char *command,char *reply,size_t capacity) {
    unsigned key=0,kind=0,role=0;uint64_t epoch=0;int n=0; const char *fields=command;
    micros_result_t rc=MICROS_ERROR_INVALID_ARGUMENT;
    if(micros_parse_prefix(&fields,"COORD B ") && micros_parse_unsigned(&fields,&key) &&
       micros_parse_unsigned(&fields,&kind) && micros_parse_unsigned(&fields,&role) &&
       micros_parse_u64(&fields,16,&epoch) && micros_parse_end(fields)) {
        rc=micros_runtime_coord_bind(owner,key,kind,role,(uint64_t)epoch);
        snprintf(reply,capacity,"COORD BOUND %d %s",(int)rc,micros_hexadecimal(micros_runtime_coord_identity(owner,key)).text);return;
    }
    n=0;
    if(sscanf(command,"COORD X %u %n",&key,&n)==1 && n) {
        uint8_t input[112],output[112];uint32_t bytes=0,got=0;int valid=1;
        const char *hex=command+n;size_t length=strlen(hex);
        if(strcmp(hex,"-")) {
            if(length%2 || length>sizeof(input)*2)valid=0;
            for(size_t i=0;valid && i<length;i+=2) {
                unsigned value=0; char pair[3]={hex[i],hex[i+1],0};
                for(unsigned j=0;j<2;++j)if(!((pair[j]>='0'&&pair[j]<='9')||(pair[j]>='a'&&pair[j]<='f')))valid=0;
                if(!valid || sscanf(pair,"%2x",&value)!=1){valid=0;break;}
                input[bytes++]=(uint8_t)value;
            }
        }
        if(valid)rc=micros_runtime_coord_exchange(owner,key,input,bytes,output,&got);
        if(!rc) {
            if(capacity<12+2*got){snprintf(reply,capacity,"COORD ERROR -1");return;}
            size_t used=(size_t)snprintf(reply,capacity,"COORD DATA ");
            for(uint32_t i=0;i<got;++i)used+=(size_t)snprintf(reply+used,capacity-used,"%02x",output[i]);
            return;
        }
    }
    snprintf(reply,capacity,"COORD ERROR %d",(int)rc);
}
#endif
