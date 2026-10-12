"""A reviewed release deploys without rebuilding against a stale local pairing."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from micros_tooling.platforms.esp8266 import cli

class ReleaseTest(unittest.TestCase):
    def test_reviewed_release_and_label_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            report=dict(base_sha256='a'*64,bank=1,graph_sha256='b'*64,plan={})
            (root/'report.json').write_text(json.dumps(report))
            (root/'bank.bin').write_bytes(b'reviewed bank')
            remote=MagicMock()
            remote.__enter__.return_value=remote
            remote.status.return_value=dict(base_sha256='a'*64)
            remote.deploy.return_value=dict(identity=dict(device_id='123456789abc'))
            args=SimpleNamespace(command='deploy',device='123456789abc',release=root,json=True)
            with patch.object(cli,'state_root',return_value=root/'state'), patch.object(cli,'connect',return_value=remote), patch.object(cli,'build') as build, patch('micros_tooling.platforms.embedded.releases.publish') as publish, contextlib.redirect_stdout(io.StringIO()):
                cli.main(args)
            build.assert_not_called()
            remote.deploy.assert_called_once_with(b'reviewed bank',report)
            publish.assert_called_once()

    def test_wrong_base_rejected_before_flash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'report.json').write_text(json.dumps(dict(base_sha256='a'*64)))
            remote=MagicMock();remote.__enter__.return_value=remote
            remote.status.return_value=dict(base_sha256='b'*64)
            args=SimpleNamespace(command='deploy',device='123456789abc',release=root,json=True)
            with patch.object(cli,'state_root',return_value=root/'state'), patch.object(cli,'connect',return_value=remote):
                with self.assertRaisesRegex(ValueError,'different base'): cli.main(args)
            remote.deploy.assert_not_called()

if __name__=='__main__': unittest.main()
