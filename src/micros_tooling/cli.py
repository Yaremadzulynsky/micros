"""One CLI boundary for checkout, installed and application launchers."""
import json
import os
from pathlib import Path
import subprocess
import sys

from micros_tooling import sdk


def source_checkout():
    """Installed packages do not themselves contain a firmware/toolchain checkout."""
    candidate = Path(__file__).resolve().parents[2]
    return candidate if all((candidate / name).exists() for name in sdk.REQUIRED) else None


def select_sdk(project):
    """Prefer an explicit checkout, then the project's link, then matching local source."""
    expected = sdk.project_revision(project) if project else None
    override = os.environ.get('MICROS_SDK')
    linked = project / '.sdk' if project else None
    explicit = Path(override).expanduser().resolve() if override else (
        linked.resolve() if linked and linked.exists() else None)
    candidate = explicit or source_checkout()
    if candidate:
        actual = sdk.git(candidate, 'rev-parse', 'HEAD')
        if expected is None or actual == expected:
            sdk.validate(candidate, actual)
            return candidate
        if explicit:
            raise ValueError(f'SDK revision differs from micros.lock: {candidate} is {actual}, project requires {expected}. Select the matching checkout with MICROS_SDK or .sdk.')
    if expected:
        return sdk.resolve(expected)
    raise ValueError('Select an SDK checkout with MICROS_SDK and run its ./micros setup before creating an application.')


def run(args):
    args = list(args)
    if os.name != 'posix':
        raise ValueError('Micros currently supports macOS and Linux hosts')
    if args == ['--version']:
        from importlib.metadata import version
        print('micros ' + version('micros-tooling'))
        return 0
    project = sdk.project_root()
    # Help can inspect the packaged parser without fetching a firmware checkout.
    help_only = not args or args in (['--help'], ['-h'], ['sdk', '--help'])
    if help_only:
        from micros_tooling import dispatch
        if project and args[:1] != ['sdk']:
            from micros_tooling.config import application
            return application.main(['--help'], project, dispatch.entrypoint)
        return dispatch.entrypoint(['--help'])
    checkout = select_sdk(project)
    if args[:1] == ['setup']:
        result = subprocess.run([str(checkout / 'micros'), *args],
            env=dict(os.environ, MICROS_PYTHON=sys.executable))
        return result.returncode
    current = source_checkout()
    if checkout != current:
        sdk.check_dependencies(checkout)
        env = dict(os.environ, MICROS_SDK=str(checkout), PYTHONPATH=str(checkout / 'src'))
        result = subprocess.run([sys.executable, '-m', 'micros_tooling.cli', *args], env=env)
        return result.returncode if result.returncode >= 0 else 128 - result.returncode
    os.environ['MICROS_SDK'] = str(checkout)
    from micros_tooling import dispatch
    if args[:1] == ['sdk']:
        os.environ.pop('MICROS_APPLICATION_ROOT', None)
        return dispatch.entrypoint(args[1:] or ['--help'])
    if project and args[:1] != ['new']:
        from micros_tooling.config import application
        os.environ['MICROS_APPLICATION_ROOT'] = str(project)
        # Relative service paths have the same meaning from every project subdirectory.
        os.chdir(project)
        return application.main(args, project, dispatch.entrypoint)
    os.environ.pop('MICROS_APPLICATION_ROOT', None)
    return dispatch.entrypoint(args)


def entrypoint():
    try:
        return run(sys.argv[1:])
    except KeyboardInterrupt:
        print('\nCancelled.', file=sys.stderr)
        return 130
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        if '--json' in sys.argv:
            print(json.dumps({'error': {'code': getattr(error, 'code', type(error).__name__),
                'message': str(error), 'details': getattr(error, 'details', None)}}), file=sys.stderr)
        else:
            print(f'micros: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(entrypoint())
