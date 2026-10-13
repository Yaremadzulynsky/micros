/* Native codec interoperability check; not a runtime admission validator. */
#include <stdio.h>
#include "pb_decode.h"
#include "pb_encode.h"
#include "wire.pb.h"

int main(void) {
    unsigned char input[193], output[192];
    size_t count = fread(input, 1, sizeof input, stdin);
    if (count > sizeof output || ferror(stdin)) return 1;
    micros_coordination_prototype_Frame frame = micros_coordination_prototype_Frame_init_zero;
    pb_istream_t reader = pb_istream_from_buffer(input, count);
    if (!pb_decode(&reader, micros_coordination_prototype_Frame_fields, &frame)) return 2;
    pb_ostream_t writer = pb_ostream_from_buffer(output, sizeof output);
    if (!pb_encode(&writer, micros_coordination_prototype_Frame_fields, &frame)) return 3;
    return fwrite(output, 1, writer.bytes_written, stdout) == writer.bytes_written ? 0 : 4;
}
