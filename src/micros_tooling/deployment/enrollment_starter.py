"""Install the SDK's hardware-independent example after console enrollment."""
import json
import os
from pathlib import Path
import shlex
import subprocess
from subprocess import run
import sys
import tempfile

from micros_tooling.config.repository import ROOT
from micros_tooling.config.scaffold import create, bind_starter
from micros_tooling.storage.packages import PackageError, require
from micros_tooling.terminal.progress import Activity


def install(result, application=None):
    # Use pristine SDK sources, never automatically run application-owned edits
    # or peripheral services merely because a new controller was enrolled.
    parent = ((Path(application) / 'build/enrollment' / result['device_id'])
              if application else Path(result['session']) / 'build')
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix='starter-', dir=parent))
    project = create(attempt / 'application', result['platform'])
    unit = bind_starter(project, result['device_id'], result['platform'], result.get('flash_mb'))
    require(unit is not None, 'Bundled starter unit could not be created.')
    arguments = ['deploy', '-d', result['device_id'], '--via', 'relay', '--project', str(unit), '--json']
    retry = shlex.join(['micros', *arguments])
    output, errors = attempt / 'deployment.json', attempt / 'deployment.log'
    environment = dict(os.environ, MICROS_SDK=str(ROOT), PYTHONPATH=str(ROOT / 'src'))
    environment.pop('MICROS_APPLICATION_ROOT', None)
    try:
        with output.open('w') as stdout, errors.open('w') as stderr, Activity('Deploying simulated climate starter'):
            completed = run([sys.executable, '-m', 'micros_tooling.cli', *arguments],
                            cwd=project, env=environment, stdout=stdout, stderr=stderr, timeout=600)
        require(completed.returncode == 0, f'Starter deployment failed; see {errors}.')
        reply = json.loads(output.read_text())
        status = reply.get('status', reply)
        activation = status.get('activation', status)
        require(status.get('identity', {}).get('device_id') == result['device_id']
                and activation.get('pending') == 0 and len(status.get('services', [])) == 3
                and all(s.get('state') in ('Running', 4) and s.get('result') == 0 for s in status['services']),
                f'Starter deployment was not confirmed; inspect {output}.')
    except (OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        # Enrollment is already confirmed. Do not revoke credentials, reflash,
        # or silently retry a possibly committed application transaction.
        raise PackageError(f'Board {result["device_id"]} is enrolled. Starter installation did not complete: {error}\n'
                           f'Inspect first: micros status -d {result["device_id"]}\n'
                           f'After checking the outcome, deploy the saved starter with: {retry}') from error
    return dict(project_unit=str(unit), confirmed=True, base_sha256=status['identity']['base_sha256'],
                graph_sha256=activation['good_sha256'], evidence=str(output))
