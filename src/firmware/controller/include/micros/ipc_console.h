#ifndef MICROS_IPC_CONSOLE_H
#define MICROS_IPC_CONSOLE_H
#include "runtime.h"
#define MICROS_IPC_BATCH_BYTES 3000u
int micros_ipc_hex(char value);
void micros_ipc_batch(micros_runtime_t *, micros_instance_t, unsigned, char *, size_t);
void micros_ipc_command(micros_runtime_t *, const micros_instance_t *, size_t,
                        const char *, char *, size_t);
#endif
