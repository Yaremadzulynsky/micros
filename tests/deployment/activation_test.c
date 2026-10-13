#include "activation.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
/* NOR faults can stop after any programmed byte. The other erase sector must
 * remain a complete old selection, including when the new marker is torn. */
int main(void)
{
    micros_activation_record_t old = micros_activation_empty();
    old.good = 0;
    memset(old.good_hash, 0x27, sizeof(old.good_hash)); /* Recognizable old content identity. */
    assert(micros_activation_seal(&old, 0));
    micros_activation_record_t next = old;
    next.candidate = 1;
    next.pending = 1;
    memset(next.candidate_hash, 0x53, sizeof(next.candidate_hash));
    assert(micros_activation_seal(&next, old.sequence));
    for (size_t cut = 0; cut <= sizeof(next); ++cut) {
        micros_activation_record_t sectors[2];
        sectors[0] = old;
        memset(&sectors[1], 0xff, sizeof(next));
        memcpy(&sectors[1], &next, cut);
        int selected = micros_activation_latest(sectors);
        assert(selected == (cut == sizeof(next) ? 1 : 0));
        assert(micros_activation_boot_bank(&sectors[selected]) == (selected ? 1u : 0u));
    }
    /* A partial erase of the stale sector also leaves the newest valid copy. */
    for (size_t cut = 0; cut <= sizeof(old); ++cut) {
        micros_activation_record_t sectors[] = {old, next};
        memset(&sectors[0], 0xff, cut);
        assert(micros_activation_latest(sectors) == 1);
    }
    for (unsigned byte = 0; byte < sizeof(next); ++byte) {
        micros_activation_record_t damaged = next;
        ((unsigned char *)&damaged)[byte] ^= 1;
        assert(!micros_activation_valid(&damaged));
    }
    next.attempts = MICROS_ACTIVATION_ATTEMPTS;
    assert(micros_activation_boot_bank(&next) == 0);
    assert(!micros_activation_seal(&next, UINT32_MAX));
    puts("All journal program/erase cuts, record corruption, attempt threshold and sequence "
         "exhaustion passed");
}
