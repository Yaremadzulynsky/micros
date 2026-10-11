#include <inttypes.h>
#include "button_state.codec.h"
/* Match the fixture channel capacity, including room for unknown protobuf fields. */
#define TEST_MESSAGE_CAPACITY 64u
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* Test bridge only: hexadecimal input/output lets Python compare the C codec
 * with Google's generated-message implementation without linking a C runtime into services. */
int main(int argc, char **argv)
{
    uint8_t bytes[TEST_MESSAGE_CAPACITY];
    uint32_t size;
    if (argc == 5) {
        micros_button_v1_ButtonState sample = {(uint32_t)strtoul(argv[1], NULL, 10), strtoull(argv[2], NULL, 10),
                                  strtoul(argv[3], NULL, 10) != 0, strtoull(argv[4], NULL, 10)};
        if (micros_button_v1_ButtonState_encode(&sample, bytes, sizeof(bytes), &size))
            return 1;
        for (uint32_t index = 0; index < size; ++index)
            printf("%02x", bytes[index]);
        puts("");
        return 0;
    }
    if (argc != 2 || strlen(argv[1]) % 2 || strlen(argv[1]) / 2 > sizeof(bytes))
        return 1;
    size = (uint32_t)strlen(argv[1]) / 2;
    for (uint32_t index = 0; index < size; ++index) {
        unsigned byte;
        if (sscanf(argv[1] + index * 2, "%2x", &byte) != 1)
            return 1;
        bytes[index] = (uint8_t)byte;
    }
    micros_button_v1_ButtonState sample;
    if (micros_button_v1_ButtonState_decode(bytes, size, &sample))
        return 1;
    printf("%" PRIu32 " %" PRIu64 " %d %" PRIu64 "\n", sample.sequence, sample.monotonic_us,
           sample.pressed, sample.publisher_started_us);
    return 0;
}
