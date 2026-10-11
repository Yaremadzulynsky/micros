#ifndef MICROS_NANOPB_CONFIG_H
#define MICROS_NANOPB_CONFIG_H
/* All consumers must use the same stream layout. IPC uses bounded memory buffers. */
#define PB_BUFFER_ONLY 1
/* Services report micros_result_t errors; omit Nanopb diagnostic strings to fit code slots. */
#define PB_NO_ERRMSG 1
/* Protobuf string fields require valid UTF-8 on both encode and decode. */
#define PB_VALIDATE_UTF8 1
#ifdef PB_ENABLE_MALLOC
#error "micros protobuf messages must use static storage, never malloc"
#endif
#endif
