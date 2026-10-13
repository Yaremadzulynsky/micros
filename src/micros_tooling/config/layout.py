"""Application paths shared by board selection and the native host lifecycle."""
from pathlib import Path


def board_units(root):
    return sorted(path for path in (Path(root) / 'units').glob('*.toml')
                  if path.name != 'host.toml')


def host_directory(project):
    """Keep host state and artifacts at the application root when the recipe lives in units/."""
    project = Path(project)
    return (project.parent.parent if project.name == 'host.toml' and project.parent.name == 'units'
            else project.parent)
