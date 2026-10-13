#ifndef MICROS_COORD_ENGINE_H
#define MICROS_COORD_ENGINE_H
#include <micros/service.h>
#include <micros/coordination.h>
#include <string.h>
/* Serialized by the owning runtime. Two bounded records, never an offline queue. */
typedef struct {
    uint64_t sequence, observed_us, applied_generation, applied_revision;
    uint32_t bytes, status;
    uint8_t data[MICROS_COORD_PAYLOAD];
} micros_coord_record_t;
typedef struct {
    uint64_t epoch;
    uint32_t kind, role; /* 0 local, 1 remote source/requester, 2 remote sink/executor */
    micros_coord_record_t primary, result;
} micros_coord_channel_t;
static inline int micros_coord_terminal(uint32_t s) { return s>=2 && s<=5; }
static inline int micros_coord_same(const micros_coord_record_t *a, const micros_coord_record_t *b) {
    return a->bytes==b->bytes && a->status==b->status &&
        a->applied_generation==b->applied_generation && a->applied_revision==b->applied_revision &&
        !memcmp(a->data,b->data,a->bytes);
}
/* A fresh advertisement refreshes receiver observation only, not proven source age. */
static inline micros_result_t micros_coord_import(micros_coord_channel_t *c,
    uint64_t epoch, const micros_coord_record_t *incoming, uint64_t now) {
    if (!c->role || c->epoch!=epoch || !incoming->sequence || incoming->bytes>MICROS_COORD_PAYLOAD)
        return MICROS_ERROR_INVALID_ARGUMENT;
    int result_direction=c->kind==MICROS_COORD_ACTION && c->role==1;
    if (!result_direction && c->role!=2) return MICROS_ERROR_UNSUPPORTED;
    micros_coord_record_t *dest=result_direction ? &c->result : &c->primary;
    if (result_direction && (incoming->sequence>c->primary.sequence ||
        incoming->status<1 || incoming->status>5)) return MICROS_ERROR_STATE;
    if (!result_direction && incoming->status) return MICROS_ERROR_INVALID_ARGUMENT;
    if (incoming->sequence<dest->sequence) return MICROS_OK;
    if (incoming->sequence==dest->sequence) {
        if (result_direction && dest->status==MICROS_COORD_ACCEPTED && micros_coord_terminal(incoming->status)) {
            *dest=*incoming;
        } else if (result_direction && micros_coord_terminal(dest->status) && incoming->status==MICROS_COORD_ACCEPTED) {
            return MICROS_OK;
        } else if (!micros_coord_same(dest,incoming)) return MICROS_ERROR_STATE;
        dest->observed_us=now;
        return MICROS_OK;
    }
    if (c->kind==MICROS_COORD_ACTION && !result_direction &&
        (incoming->sequence!=dest->sequence+1 || (dest->sequence &&
         (c->result.sequence!=dest->sequence || !micros_coord_terminal(c->result.status)))))
        return MICROS_ERROR_STATE;
    *dest=*incoming; dest->observed_us=now;
    return MICROS_OK;
}
#endif
