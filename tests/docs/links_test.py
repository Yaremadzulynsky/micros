"""Repository navigation must survive source and guide moves."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('docs_hooks', ROOT / 'tools/docs/hooks.py')
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)


class DocumentationLinks(unittest.TestCase):
    def test_current_entry_points(self):
        hooks.check_entry_points()

    def test_application_template_sdk_links_are_checked_against_framework(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / 'tools/templates/application'
            template.mkdir(parents=True)
            guide = template / 'AGENTS.md'
            guide.write_text('[Framework](.sdk/AGENTS.md)\n')
            (root / 'AGENTS.md').touch()
            hooks.check_local_links(guide, root)
            guide.write_text('[Missing workflow](.sdk/tools/skills/missing/SKILL.md)\n')
            with self.assertRaisesRegex(ValueError, 'Missing repository link'):
                hooks.check_local_links(guide, root)

    def test_source_move_breaks_navigation_until_link_is_updated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / 'README.md'
            old = root / 'old.md'
            old.touch()
            guide.write_text('[Guide](old.md#section)\n')
            hooks.check_local_links(guide, root)
            old.rename(root / 'new.md')
            with self.assertRaisesRegex(ValueError, 'README.md: old.md#section'):
                hooks.check_local_links(guide, root)
            guide.write_text('[Guide](new.md#section)\n')
            hooks.check_local_links(guide, root)

    def test_urls_anchors_and_code_examples_are_not_local_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / 'README.md'
            guide.write_text('[Site](https://example.com) [Section](#section)\n'
                             '```md\n[Example](missing.md)\n```\n')
            hooks.check_local_links(guide, root)


if __name__ == '__main__':
    unittest.main()
