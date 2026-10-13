"""Modern pin declarations emit an explicit no-pull binding on every platform."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from micros_tooling.platforms.samd21.board import definition as samd
from micros_tooling.platforms.esp8266.board import definition as esp8266
from micros_tooling.config.resources import load_board
from micros_tooling.storage.packages import PackageError

class EmbeddedPinDeclarations(unittest.TestCase):
 def test_explicit_none_preserves_graph_and_fingerprint(self):
  for profile,resolve in [('arduino_mkr_wifi_1010',samd),('esp8266_4mb',esp8266)]:
   board=dict(profile=profile,gpio=dict(led=dict(pin=13,direction='output'),button=dict(pin=12,direction='input')))
   expected=resolve(board)
   for binding in board['gpio'].values():binding['pull']='none'
   self.assertEqual(resolve(board),expected)
   root=dict(board=dict(profile=profile),services=dict(app=dict(gpio_bindings=board['gpio'])))
   self.assertEqual(load_board(Path('unused.toml'),root),expected)
 def test_unsupported_pull_is_not_silently_dropped(self):
  for profile,resolve in [('arduino_mkr_wifi_1010',samd),('esp8266_4mb',esp8266)]:
   for pull in ('up','down','invalid'):
    with self.subTest(profile=profile,pull=pull),self.assertRaises(PackageError):
     resolve(dict(profile=profile,gpio=dict(button=dict(pin=12,direction='input',pull=pull))))
if __name__=='__main__':unittest.main()
