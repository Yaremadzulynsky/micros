"""Compare the bounded C ButtonState codec with Google's official protobuf implementation."""
import random
import subprocess
import sys
from pathlib import Path
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

# Build both implementations from the actual proto; no mirrored field definitions.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from micros_tooling.config.protobuf import compile_schema
schema = compile_schema(ROOT / "src/sdk/protos/button/v1/button_state.proto")
pool = descriptor_pool.DescriptorPool()
for description in descriptor_pb2.FileDescriptorSet.FromString(schema["descriptor"]).file:
    pool.Add(description)
ButtonState = message_factory.GetMessageClass(pool.FindMessageTypeByName('micros.button.v1.ButtonState'))
codec = sys.argv[1]
def call(*arguments, success=True):
    result = subprocess.run([codec, *map(str, arguments)], text=True, capture_output=True, timeout=5)
    assert (result.returncode == 0) == success, (arguments, result)
    return result.stdout.strip()

# Edge widths, both button states, and reproducible random scalar combinations.
randomizer = random.Random(3)  # Fixed seed keeps the interoperability corpus repeatable.
cases = [(0, 0, 0), (1, 1, 1), (2**32-1, 2**64-1, 1), (1, 127, 0)]
cases += [(randomizer.randrange(2**32), randomizer.randrange(2**64), randomizer.randrange(2)) for _ in range(32)]
for sequence, timestamp, value in cases:
    epoch = randomizer.randrange(2**64)
    sample = ButtonState(sequence=sequence, monotonic_us=timestamp, pressed=value, publisher_started_us=epoch)
    encoded = sample.SerializeToString()
    assert bytes.fromhex(call(sequence, timestamp, value, epoch)) == encoded
    assert call(encoded.hex()) == f'{sequence} {timestamp} {value} {epoch}'
# Unknown varint/fixed64/length-delimited/fixed32 fields and duplicate scalar last-wins.
for suffix in ('2001', '290000000000000000', '3203616263', '3d00000000', '0802', '1801', '1800', '1802', '18ffffffffffffffffff01', '18011800'):
    encoded = bytes.fromhex('0801' + suffix)
    expected = ButtonState.FromString(encoded)
    assert call(encoded.hex()) == f'{expected.sequence} {expected.monotonic_us} {int(expected.pressed)} {expected.publisher_started_us}'
# Truncated varints, overflow, field zero, wrong known-field wire type, length overflow.
for malformed in ('08', '0880', '088080808080808080808002', '00', '0a00', '2205ff', '08ffffffff1f', '23'):
    call(malformed, success=False)
print('PASS 36 protobuf interoperability vectors, unknown/duplicate fields, and malformed-input rejection')
