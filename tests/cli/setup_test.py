"""Exercise the real bootstrap shell without network, sudo or host installations."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

# Every external prerequisite/installer is a fake executable. Only basic shell
# utilities come from the host. State changes model successful package installs.
FAKE = r'''
import json, os, pathlib, sys
state_path = pathlib.Path(os.environ['SETUP_STATE'])
s = json.loads(state_path.read_text())
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['SETUP_LOG'], 'a') as log:
    log.write(json.dumps([name, *args]) + '\n')
def save(): state_path.write_text(json.dumps(s))
def success(key): sys.exit(0 if s.get(key, False) else 1)
if name == 'uname': print(s.get('os', 'Linux'))
elif name == 'id': print('0')
elif name == 'git': success('git')
elif name in ('cc', 'c++'): success('compiler')
elif name == 'make': success('make')
elif name == 'cmake': print('cmake version ' + s.get('cmake', '0.0.0'))
elif name == 'ninja': success('ninja')
elif name == 'xcode-select':
    if args == ['--install']: sys.exit(0)
    success('compiler')
elif name == 'apt-cache':
    sys.exit(0 if s.get('python_available', True) and '3.12' in args[-1] else 1)
elif name in ('apt-get', 'dnf', 'brew'):
    if s.get('install_fail'): sys.exit(23)
    if args[0] == '--prefix': print(os.environ['SETUP_BIN_PARENT'])
    elif args[0] == 'install':
        for package in args[1:]:
            if package == 'git': s['git'] = True
            if package in ('build-essential', 'gcc', 'gcc-c++', 'make'):
                s['compiler'] = True; s['make'] = True
            if package.startswith('python'): s['python'] = True; s['venv'] = True
        save()
elif name.startswith('python'):
    if args[0] == '-c':
        if 'check_dependencies' in args[1]: success('deps')
        if 'import venv' in args[1]: success('venv')
        if 'print("python%d.%d"' in args[1]: print('python3.12')
        else: success('python')
    elif args[:2] == ['-m', 'venv']:
        target = pathlib.Path(args[2]) / 'bin/python'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(pathlib.Path(sys.argv[0]).resolve())
    elif args[:3] == ['-m', 'pip', 'check']: success('deps')
    elif args[:3] == ['-m', 'pip', 'install']:
        if s.get('pip_fail'): sys.exit(24)
        if '-r' in args: s['deps'] = True
        if any(a.startswith('cmake>=') for a in args): s['cmake'] = '3.30.0'
        if any(a.startswith('ninja>=') for a in args): s['ninja'] = True
        save()
else: sys.exit('unexpected fake command: ' + name)
'''


class SetupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='micros setup ')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'sdk with spaces'
        (self.root / 'tools').mkdir(parents=True)
        shutil.copy(ROOT / 'tools/setup.sh', self.root / 'tools/setup.sh')
        shutil.copy(ROOT / 'micros', self.root / 'micros')
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.state = self.base / 'state.json'
        self.log = self.base / 'commands.jsonl'
        self.env = {'PATH': str(self.bin), 'SETUP_STATE': str(self.state),
                    'SETUP_LOG': str(self.log), 'SETUP_BIN_PARENT': str(self.base),
                    'TMPDIR': str(self.base)}
        for name in ('dirname', 'mktemp', 'rm', 'awk', 'sh'):
            (self.bin / name).symlink_to(shutil.which(name))
        for name in ('uname', 'id', 'git', 'cc', 'c++', 'cmake', 'ninja', 'make',
                     'python3.12', 'python3.11', 'python3.10', 'python3', 'apt-get', 'apt-cache', 'xcode-select'):
            self.fake(name)
        self.set_state()

    def fake(self, name):
        p = self.bin / name
        p.write_text('#!' + sys.executable + '\n' + FAKE)
        p.chmod(0o755)

    def set_state(self, **overrides):
        state = dict(git=True, python=True, venv=True, compiler=True, make=True,
                     cmake='3.30.0', ninja=True, deps=True)
        state.update(overrides)
        self.state.write_text(json.dumps(state))

    def environment(self):
        p = self.root / 'build/python/bin/python'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.symlink_to(self.bin / 'python3.12')

    def run_setup(self, *args, code=0):
        result = subprocess.run(['/bin/sh', str(self.root / 'micros'), 'setup', *args],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_check_ready_does_not_install(self):
        self.environment()
        self.assertIn('Ready for', self.run_setup('--check'))
        self.assertFalse(any('install' in c or 'update' in c for c in self.commands()))

    def test_check_missing_reports_all_and_does_not_create_environment(self):
        self.set_state(git=False, python=False, compiler=False, make=False, cmake='3.22.0', ninja=False)
        text = self.run_setup('--check', code=1)
        self.assertEqual(text.count('MISSING'), 8)
        self.assertFalse((self.root / 'build').exists())
        self.assertFalse(any('install' in c or 'update' in c for c in self.commands()))

    def test_apt_installs_then_rechecks_missing_prerequisites(self):
        self.set_state(git=False, python=False, venv=False, compiler=False, make=False,
                       cmake='3.22.0', ninja=False, deps=False)
        self.assertIn('Ready. Create', self.run_setup())
        cmds = self.commands()
        self.assertIn(['apt-get', 'install', '-y', 'git', 'build-essential',
                       'python3.12', 'python3.12-venv'], cmds)
        self.assertTrue(any('cmake>=3.24,<5' in c for c in cmds))
        self.assertTrue(any('ninja>=1.11,<2' in c for c in cmds))
        self.assertIn('Ready for', self.run_setup('--check'))

    def test_missing_venv_installs_package_for_selected_python(self):
        self.set_state(venv=False)
        self.run_setup()
        self.assertIn(['apt-get', 'install', '-y', 'python3.12', 'python3.12-venv'], self.commands())

    def test_dnf_installation(self):
        (self.bin / 'apt-get').unlink()
        self.fake('dnf')
        self.set_state(python=False, compiler=False)
        self.run_setup()
        self.assertIn(['dnf', 'install', '-y', 'gcc', 'gcc-c++', 'make', 'python3.12'], self.commands())

    def test_homebrew_installs_supported_python(self):
        self.fake('brew')
        self.set_state(os='Darwin', python=False)
        self.run_setup()
        self.assertIn(['brew', 'install', 'python@3.12'], self.commands())

    def test_check_on_fresh_mac_does_not_launch_apple_tool_shims(self):
        self.set_state(os='Darwin', compiler=False)
        self.run_setup('--check', code=1)
        self.assertFalse(any(c[0] in ('cc', 'c++', 'git', 'make') or '--install' in c
                             for c in self.commands()))

    def test_apple_installer_requires_completion_before_success(self):
        self.set_state(os='Darwin', compiler=False)
        text = self.run_setup(code=1)
        self.assertIn('Complete the Apple Command Line Tools installer', text)
        self.assertNotIn('Ready. Create', text)

    def test_install_failure_does_not_claim_ready(self):
        self.set_state(git=False, install_fail=True)
        self.assertNotIn('Ready. Create', self.run_setup(code=23))
        self.assertFalse((self.root / 'build').exists())

    def test_pip_failure_does_not_claim_ready(self):
        self.set_state(deps=False, pip_fail=True)
        self.assertNotIn('Ready. Create', self.run_setup(code=24))

    def test_unsupported_distribution_explains_manual_path(self):
        (self.bin / 'apt-get').unlink()
        self.set_state(python=False)
        self.assertIn('Install the missing tools with your package manager', self.run_setup(code=1))

    def test_unsupported_python_repository_does_not_add_external_repository(self):
        self.set_state(python=False, python_available=False)
        self.assertIn('no supported Python', self.run_setup(code=1))
        self.assertFalse(any('install' in c for c in self.commands()))

    def test_existing_invalid_environment_is_preserved(self):
        self.environment()
        marker = self.root / 'build/python/keep'
        marker.write_text('user state')
        self.set_state(python=False)
        self.assertIn('has been preserved', self.run_setup(code=1))
        self.assertEqual(marker.read_text(), 'user state')
        self.assertFalse(any('install' in c for c in self.commands()))

    def test_invalid_override_does_not_install_unrequested_python(self):
        self.env['MICROS_PYTHON'] = '/nonexistent/python'
        self.assertIn('Correct or unset it', self.run_setup(code=1))
        self.assertFalse(any('install' in c for c in self.commands()))

    def test_invalid_options_are_rejected_before_probing(self):
        self.run_setup('--unknown', code=2)
        self.run_setup('--check', '--esp32', code=2)
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
