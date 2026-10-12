"""Run the immutable trust-buffer ownership check against the prepared SDK.

After build_esp8266.py has prepared the pinned SDK and trust header, run:
python tests/esp8266/tls_trust_check.py SDK_PATH BASE_BUILD_PATH
"""
from pathlib import Path
import subprocess
import sys
import tempfile

sdk, output = (Path(value).resolve() for value in sys.argv[1:])
tls = sdk / 'components/mbedtls/mbedtls'
with tempfile.TemporaryDirectory(prefix='micros-tls-trust-') as directory:
    build = Path(directory)
    subprocess.run(['cmake', '-S', str(tls), '-B', str(build),
                    '-DCMAKE_POLICY_VERSION_MINIMUM=3.5', '-DENABLE_TESTING=OFF',
                    '-DENABLE_PROGRAMS=OFF', '-DCMAKE_C_FLAGS=-fsanitize=address'], check=True)
    subprocess.run(['cmake', '--build', str(build), '-j', '4'], check=True)
    executable = build / 'trust-test'
    subprocess.run(['cc', '-fsanitize=address', '-g', '-I'+str(tls/'include'),
                    '-I'+str(output/'trust'), str(Path(__file__).with_name('tls_trust_test.c')),
                    str(build/'library/libmbedx509.a'), str(build/'library/libmbedcrypto.a'),
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable), str(output/'trust/relay-roots.pem')], check=True)
