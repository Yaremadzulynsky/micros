"""One board-independent generation operation for text and JSON clients."""
import json
from pathlib import Path
from micros_tooling.config.artifacts import publish, service_directory
from micros_tooling.config.service_generation import artifacts, contract_path
from micros_tooling.storage.packages import require


def run(root, service=None, output=None, json_output=False):
    root = Path(root).resolve()
    contracts = [contract_path(service)] if service else sorted((root / 'services').glob('**/service.toml'))
    require(bool(contracts), f'No service contracts under {root / "services"}')
    require(output is None or len(contracts) == 1, '--output requires one --service')
    plans, reports = [], []
    for path in contracts:
        destination = Path(output).resolve() if output else service_directory(root, path) / 'generated'
        files = artifacts(path, destination)
        plans.append((destination, str(path.resolve()), files))
        reports.append(dict(contract=str(path.resolve()), output=str(destination), files=sorted(files)))
    publish(plans)
    report = dict(format=1, operation='generate', services=reports)
    if json_output: print(json.dumps(report, indent=2))
    else:
        for item in reports: print(f"{item['contract']}: {item['output']} ({len(item['files'])} files)")
        print('Service interfaces generated; no board selected.')
    return report
