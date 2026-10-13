/* Included after private resource helpers: all entry points hold the runtime lock. */
static micros_result_t api_coord_open(micros_context_t *ctx, uint32_t key, uint32_t access,
                                     uint32_t kind, micros_handle_t *handle)
{
    if (kind<1 || kind>3) return MICROS_ERROR_INVALID_ARGUMENT;
    micros_result_t rc=api_ipc_open(ctx,key,access,handle);
    if (rc) return rc;
    micros_runtime_t *r=ctx->runtime;
    micros_platform_lock(r->sync);
    resource_slot_t *p=find_resource(ctx,*handle,access==MICROS_IPC_PUBLISH ? RESOURCE_PUBLISHER : RESOURCE_SUBSCRIBER);
    micros_channel_t *ch=resource_channel(r,p);
    if (!ch) { micros_platform_unlock(r->sync); api_ipc_close(ctx,*handle); return MICROS_ERROR_STALE_HANDLE; }
    micros_coord_channel_t *c=r->coordination[p->channel_slot];
    if (ch->policy!=MICROS_CHANNEL_LATEST || ch->payload_bytes>MICROS_COORD_PAYLOAD ||
        (c && c->kind && c->kind!=kind)) rc=MICROS_ERROR_INVALID_ARGUMENT;
    for (unsigned i=0; !rc && i<MICROS_RUNTIME_HANDLE_CAPACITY; ++i) {
        resource_slot_t *other=&r->resources[i];
        if (other!=p && other->owner && other->kind==p->kind && other->channel_slot==p->channel_slot &&
            other->channel_generation==p->channel_generation &&
            (access==MICROS_IPC_PUBLISH || kind==MICROS_COORD_ACTION)) rc=MICROS_ERROR_STATE;
    }
    if (!rc && !c) {
        c = micros_memory_allocate(sizeof(*c));
        if (!c) rc = MICROS_ERROR_CAPACITY;
        else { memset(c, 0, sizeof(*c)); r->coordination[p->channel_slot] = c; }
    }
    if (!rc) { c->kind=kind; if (!c->epoch) c->epoch=micros_platform_now_us()+key; p->next_sequence=1; p->line=kind; }
    micros_platform_unlock(r->sync);
    if (rc) { api_ipc_close(ctx,*handle); *handle=0; }
    return rc;
}
static micros_result_t api_coord(micros_context_t *ctx, micros_handle_t handle, uint32_t op,
    uint8_t *payload, uint32_t capacity, uint32_t *bytes, micros_coord_info_t *info)
{
    if (!payload || !bytes || !info || op<1 || op>8) return MICROS_ERROR_INVALID_ARGUMENT;
    int publisher=op==MICROS_COORD_SET || op==MICROS_COORD_REQUEST || op==MICROS_COORD_RESULT || op==MICROS_COORD_EMIT;
    uint32_t kind=(op==1 || op==2) ? MICROS_COORD_STATE : (op<=6 ? MICROS_COORD_ACTION : MICROS_COORD_EVENT);
    micros_runtime_t *r=ctx->runtime;
    micros_platform_lock(r->sync);
    resource_slot_t *p=find_resource(ctx,handle,publisher ? RESOURCE_PUBLISHER : RESOURCE_SUBSCRIBER);
    micros_channel_t *ch=resource_channel(r,p);
    micros_result_t rc=MICROS_OK;
    if (!ch || p->line!=kind) rc=MICROS_ERROR_STALE_HANDLE;
    else if (r->usage.reboot_required || ctx->service->stop_requested) rc=MICROS_ERROR_STATE;
    if (rc) { micros_platform_unlock(r->sync); return rc; }
    micros_coord_channel_t *c=r->coordination[p->channel_slot];
    micros_coord_record_t *a=&c->primary, *b=&c->result;
    uint64_t now=micros_platform_now_us();
    int write=op==1 || op==3 || op==5 || op==7;
    if (write && (*bytes>capacity || *bytes>ch->payload_bytes)) rc=MICROS_ERROR_CAPACITY;
    if (!rc && (op==1 || op==3 || op==7)) {
        if (c->role==2) rc=MICROS_ERROR_UNSUPPORTED;
        else if (op==3 && a->sequence && (b->sequence!=a->sequence || !micros_coord_terminal(b->status))) rc=MICROS_ERROR_STATE;
        else if (a->sequence==UINT64_MAX) rc=MICROS_ERROR_CAPACITY;
        else if (op!=1 || !a->sequence || a->bytes!=*bytes || memcmp(a->data,payload,*bytes) ||
                 a->applied_generation!=info->applied_generation || a->applied_revision!=info->applied_revision) {
            ++a->sequence; a->bytes=*bytes; memcpy(a->data,payload,*bytes); a->observed_us=now;
            a->applied_generation=info->applied_generation; a->applied_revision=info->applied_revision;
        }
        info->generation=c->epoch; info->revision=a->sequence;
    } else if (!rc && op==5) {
        if (c->role==1 || info->generation!=c->epoch || info->revision!=a->sequence ||
            b->sequence!=a->sequence || b->status!=MICROS_COORD_ACCEPTED || !micros_coord_terminal(info->status)) rc=MICROS_ERROR_STATE;
        else { b->bytes=*bytes; memcpy(b->data,payload,*bytes); b->status=info->status; b->observed_us=now; }
    } else if (!rc) {
        micros_coord_record_t *record=op==6 ? b : a;
        if (!record->sequence || (op==6 && record->sequence!=a->sequence)) rc=MICROS_ERROR_EMPTY;
        else if (record->bytes>capacity) rc=MICROS_ERROR_CAPACITY;
        else if (op==4 && b->sequence==a->sequence) rc=MICROS_ERROR_EMPTY;
        else if ((op==2 || op==8) && record->sequence<p->next_sequence) rc=MICROS_ERROR_EMPTY;
        if (!rc) {
            memcpy(payload,record->data,record->bytes); *bytes=record->bytes;
            *info=(micros_coord_info_t){.generation=c->epoch,.revision=record->sequence,
                .applied_generation=record->applied_generation,.applied_revision=record->applied_revision,
                .observation_age_us=now-record->observed_us,.status=record->status};
            if (op==4) { memset(b,0,sizeof(*b)); b->sequence=a->sequence; b->status=MICROS_COORD_ACCEPTED; b->observed_us=now; }
            if (op==2 || op==8) p->next_sequence=record->sequence==UINT64_MAX ? UINT64_MAX : record->sequence+1;
        }
    }
    micros_platform_unlock(r->sync);
    return rc;
}
/* Transport framing is fixed LE metadata + application protobuf. No struct memcpy:
 * ESP32 and ESP8266 alignment/endianness never define wire bytes. */
static void coord_put(uint8_t *p,uint64_t v,unsigned n) { for(unsigned i=0;i<n;++i) p[i]=(uint8_t)(v>>(8*i)); }
static uint64_t coord_get(const uint8_t *p,unsigned n) { uint64_t v=0;for(unsigned i=0;i<n;++i)v|=(uint64_t)p[i]<<(8*i);return v; }
static unsigned coord_encode(micros_coord_channel_t *c,micros_coord_record_t *record,uint8_t *out) {
    if(!record->sequence) return 0;
    memcpy(out,"MCO1",4); out[4]=(uint8_t)c->kind;out[5]=0;coord_put(out+6,record->bytes,2);
    coord_put(out+8,c->epoch,8);coord_put(out+16,record->sequence,8);coord_put(out+24,record->status,4);
    coord_put(out+28,0,4);coord_put(out+32,record->applied_generation,8);coord_put(out+40,record->applied_revision,8);
    memcpy(out+48,record->data,record->bytes);return 48+record->bytes;
}
micros_result_t micros_runtime_coord_exchange(micros_runtime_t *r,uint32_t key,
    const uint8_t *input,uint32_t bytes,uint8_t *output,uint32_t *output_bytes)
{
    if(!r || !output || !output_bytes || (bytes && !input)) return MICROS_ERROR_INVALID_ARGUMENT;
    micros_result_t rc=MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(r->sync);
    for(unsigned slot=0;slot<MICROS_CHANNEL_CAPACITY;++slot) {
        if(!r->channels[slot].key || r->channels[slot].key!=key)continue;
        micros_coord_channel_t *c=r->coordination[slot];
        if(!c || !c->role || r->usage.reboot_required)break;
        rc=MICROS_OK;
        if(bytes) {
            if(bytes<48 || bytes>112 || memcmp(input,"MCO1",4) || input[4]!=c->kind || input[5] ||
                coord_get(input+28,4) || coord_get(input+6,2)!=bytes-48 || bytes-48>r->channels[slot].payload_bytes) rc=MICROS_ERROR_INVALID_ARGUMENT;
            else {
                micros_coord_record_t record={.sequence=coord_get(input+16,8),.bytes=bytes-48,
                    .status=(uint32_t)coord_get(input+24,4),.applied_generation=coord_get(input+32,8),
                    .applied_revision=coord_get(input+40,8)};
                memcpy(record.data,input+48,record.bytes);
                rc=micros_coord_import(c,coord_get(input+8,8),&record,micros_platform_now_us());
            }
        }
        *output_bytes=0;
        if(!rc && (c->role==1 || c->kind==MICROS_COORD_ACTION))
            *output_bytes=coord_encode(c,c->role==1 ? &c->primary : &c->result,output);
        break;
    }
    micros_platform_unlock(r->sync);return rc;
}
micros_result_t micros_runtime_coord_bind(micros_runtime_t *r,uint32_t key,uint32_t kind,uint32_t role,uint64_t epoch)
{
    if(!r || (!epoch && role!=1) || kind<1 || kind>3 || role<1 || role>2) return MICROS_ERROR_INVALID_ARGUMENT;
    micros_result_t rc=MICROS_ERROR_INVALID_ARGUMENT;
    micros_platform_lock(r->sync);
    for(unsigned slot=0;slot<MICROS_CHANNEL_CAPACITY;++slot) {
        if(!r->channels[slot].key || r->channels[slot].key!=key)continue;
        micros_coord_channel_t *c=r->coordination[slot];
        if (!c) break;
        if (!epoch && role==1) epoch=c->epoch;
        if(c->kind!=kind || (c->role && (c->role!=role || c->epoch!=epoch)))break;
        int count=0,invalid=0;
        for(unsigned i=0;i<MICROS_RUNTIME_HANDLE_CAPACITY;++i) {
            resource_slot_t *p=&r->resources[i];
            if((p->kind!=RESOURCE_PUBLISHER && p->kind!=RESOURCE_SUBSCRIBER) || !p->owner ||
                p->channel_slot!=slot || p->channel_generation!=r->channels[slot].generation)continue;
            if(p->line!=kind || p->kind!=(role==1 ? RESOURCE_PUBLISHER : RESOURCE_SUBSCRIBER))invalid=1;
            ++count;
        }
        if(invalid || !count || r->usage.reboot_required)break;
        c->epoch=epoch;c->role=role;rc=MICROS_OK;break;
    }
    micros_platform_unlock(r->sync);return rc;
}

uint64_t micros_runtime_coord_identity(micros_runtime_t *r,uint32_t key) {
    if (!r) return 0;
    uint64_t epoch=0;micros_platform_lock(r->sync);
    for(unsigned slot=0;slot<MICROS_CHANNEL_CAPACITY;++slot)
        if(key && r->channels[slot].key==key && r->coordination[slot])epoch=r->coordination[slot]->epoch;
    micros_platform_unlock(r->sync);return epoch;
}
