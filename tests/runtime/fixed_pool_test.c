#include "../../src/firmware/kernel/support/fixed_pool.h"
#include <assert.h>
#include <stdalign.h>
#include <stdio.h>
int main(void) {
    alignas(16) unsigned char memory[512] = {0};
    void *a = micros_pool_take(memory, sizeof(memory), 1);
    void *b = micros_pool_take(memory, sizeof(memory), 127);
    void *c = micros_pool_take(memory, sizeof(memory), 64);
    assert(a && b && c && !((uintptr_t)a % 16) && !((uintptr_t)b % 16));
    memset(b, 0xa5, 127);
    assert(!micros_pool_take(memory, sizeof(memory), SIZE_MAX));
    assert(!micros_pool_take(memory, sizeof(memory), 512));
    assert(!micros_pool_release(memory, sizeof(memory), (char *)b + 1));
    for (int i = 0; i < 127; ++i) assert(((unsigned char *)b)[i] == 0xa5);
    assert(micros_pool_release(memory, sizeof(memory), a));
    assert(!micros_pool_release(memory, sizeof(memory), a));
    assert(micros_pool_release(memory, sizeof(memory), c));
    assert(micros_pool_release(memory, sizeof(memory), b));
    assert(micros_pool_available(memory, sizeof(memory)) == 496);
    for (int cycle = 0; cycle < 1000; ++cycle) {
        a = micros_pool_take(memory, sizeof(memory), 496);
        assert(a && !micros_pool_take(memory, sizeof(memory), 1));
        for (int i = 0; i < 496; ++i) assert(((unsigned char *)a)[i] == 0);
        memset(a, 0xff, 496);
        assert(micros_pool_release(memory, sizeof(memory), a));
    }
    puts("fixed pool bounds, ownership, coalescing and reuse passed");
}
