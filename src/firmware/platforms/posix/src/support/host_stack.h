#ifndef MICROS_HOST_STACK_H
#define MICROS_HOST_STACK_H
#include <stddef.h>
#include <unistd.h>
/** Host libc/thread frames need 64 KiB; Linux ARM64 may require more for its
 * dynamic vector-state ABI. sysconf supplies that runtime minimum. */
static inline size_t micros_host_stack_floor(void)
{
    const size_t policy_bytes = 64u * 1024u;
    long platform_bytes = sysconf(_SC_THREAD_STACK_MIN);
    return platform_bytes > 0 && (size_t)platform_bytes > policy_bytes ? (size_t)platform_bytes
                                                                       : policy_bytes;
}
#endif
