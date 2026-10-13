"""Reject real compiler-produced constructor, TLS, dependency and resolver libraries."""

from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.storage.native_image import envelope, NATIVE_HOST_TARGET

host, compiler = sys.argv[1:]
fixtures = {
    "constructor": '__attribute__((constructor)) static void startup(void) { __asm__ volatile("" ::: "memory"); }',
    "tls": "__thread int state; int read_state(void) { return state; }",
    "import": "extern int external_api(void); int call_api(void) { return external_api(); }",
    "resolver": 'static int implementation(void) { return 1; } static void *resolve(void) { return implementation; } int indirect(void) __attribute__((ifunc("resolve")));',
}
with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    for name, source in fixtures.items():
        code, library, image = (
            directory / (name + suffix) for suffix in (".c", ".so", ".mimg")
        )
        code.write_text(source)
        subprocess.run(
            [compiler, "-shared", "-fPIC", "-nostdlib", str(code), "-o", str(library)],
            check=True,
        )
        image.write_bytes(envelope(NATIVE_HOST_TARGET, library.read_bytes()))
        result = subprocess.run(
            [host, str(image)], capture_output=True, text=True, timeout=5
        )
        assert result.returncode and "REJECT ELF" in result.stderr, (
            name,
            result.stdout,
            result.stderr,
        )
print(
    "Real ELF constructor, TLS, import and IFUNC fixtures rejected before native loading"
)
