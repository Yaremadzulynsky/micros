#include <assert.h>
#include "button_state.codec.h"
/* Match the fixture channel capacity, including room for unknown protobuf fields. */
#define TEST_MESSAGE_CAPACITY 64u
#include <stdio.h>
#include <string.h>
/* xorshift32 uses the standard full-period shift triplet (13, 17, 5).
 * An arbitrary nonzero seed makes 20,000 bounded trials reproducible and quick. */
static uint32_t random_word = UINT32_C(0x93a71);
static uint32_t next_random(void)
{
    random_word ^= random_word << 13;
    random_word ^= random_word >> 17;
    random_word ^= random_word << 5;
    return random_word;
}
int main(void)
{
    uint8_t buffer[TEST_MESSAGE_CAPACITY];
    memset(buffer, 0xa5, sizeof(buffer)); /* Distinct unwritten-output sentinel. */
    micros_button_v1_ButtonState maximum = {UINT32_MAX, UINT64_MAX, true, UINT64_MAX}, decoded;
    uint32_t size;
    assert(micros_button_v1_ButtonState_encode(&maximum, buffer, 1, &size) == MICROS_ERROR_CAPACITY);
    assert(size == 30); /* Four tags plus 5-byte uint32, two uint64 varints and bool. */
    for (size_t index = 0; index < sizeof(buffer); ++index)
        assert(buffer[index] == 0xa5);
    assert(!micros_button_v1_ButtonState_encode(&maximum, buffer, size, &size));
    assert(!micros_button_v1_ButtonState_decode(buffer, size, &decoded));
    assert(decoded.sequence == maximum.sequence && decoded.monotonic_us == maximum.monotonic_us &&
           decoded.pressed == maximum.pressed && decoded.publisher_started_us == maximum.publisher_started_us);
    for (unsigned trial = 0; trial < 20000; ++trial) {
        uint32_t length = next_random() % (TEST_MESSAGE_CAPACITY + 1);
        for (uint32_t index = 0; index < length; ++index)
            buffer[index] = (uint8_t)next_random();
        decoded = maximum;
        micros_result_t result = micros_button_v1_ButtonState_decode(buffer, length, &decoded);
        if (result) {
            assert(decoded.sequence == maximum.sequence &&
                   decoded.monotonic_us == maximum.monotonic_us &&
                   decoded.pressed == maximum.pressed && decoded.publisher_started_us == maximum.publisher_started_us);
        } else {
            uint8_t encoded[TEST_MESSAGE_CAPACITY];
            micros_button_v1_ButtonState roundtrip;
            assert(!micros_button_v1_ButtonState_encode(&decoded, encoded, sizeof(encoded), &size));
            assert(!micros_button_v1_ButtonState_decode(encoded, size, &roundtrip));
            assert(roundtrip.sequence == decoded.sequence &&
                   roundtrip.monotonic_us == decoded.monotonic_us &&
                   roundtrip.pressed == decoded.pressed && roundtrip.publisher_started_us == decoded.publisher_started_us);
        }
    }
    puts(
        "PASS codec capacity/immutability/extreme values and 20000 bounded malformed-input trials");
}
