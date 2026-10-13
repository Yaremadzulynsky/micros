"""Run the real shared RPC controller against full libc and ARM newlib-nano."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]

class RpcIntegerTests(unittest.TestCase):
    def run_controller(self, compiler, extra, emulator=None):
        fw=ROOT/'src/firmware'
        includes=[ROOT/'tests/platforms/fake', fw/'contracts/include', ROOT/'src/sdk/abi/include', fw/'controller/include']
        includes += [fw/'kernel'/p for p in ('runtime','ipc','loader','deployment','hash')]
        sources=[ROOT/'tests/platforms/rpc_integer_test.c']
        sources += [fw/'controller'/p for p in ('deployment.c','application.c','status.c','protocol/ipc_console.c')]
        sources += [fw/'kernel'/p for p in ('runtime/runtime.c','ipc/channel.c','loader/image.c','loader/elf.c','deployment/activation.c','hash/sha256.c')]
        sources += [ROOT/'tests/platforms/fake/src'/p for p in ('platform.c','storage.c','transport.c')]
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'rpc.elf'
            subprocess.run([compiler, *extra, '-std=c17','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                *['-I'+str(p) for p in includes], *map(str,sources), '-o',str(output)],check=True)
            command=([emulator,'-M','versatilepb','-cpu','arm926','-nographic','-semihosting','-kernel'] if emulator else [])+[str(output)]
            result=subprocess.run(command,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('portable RPC and status passed',result.stdout+result.stderr)

    def test_native_controller(self): self.run_controller('cc',[])
    def test_nano_controller(self):
        compiler=os.environ.get('MICROS_ARM_GCC') or shutil.which('arm-none-eabi-gcc')
        emulator=shutil.which('qemu-system-arm')
        if not compiler or not emulator:
            if os.environ.get('MICROS_REQUIRE_NANO_TEST'): self.fail('ARM GCC and QEMU required')
            self.skipTest('ARM GCC/QEMU unavailable')
        # ARM9 semihosting runs the reduced libc with inert hardware. Select the
        # 32-bit ARM ABI headers; this fixture never loads native service code.
        self.run_controller(compiler,['-mcpu=arm926ej-s','-mthumb','-D__ARM_ARCH_6M__=1','--specs=rdimon.specs','--specs=nano.specs'],emulator)

if __name__=='__main__': unittest.main()
