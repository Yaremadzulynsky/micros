"""Channel discovery remains independent of retired presentation metadata."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'src'))
from channel_fixture import make_device
from micros_tooling.communication.channel_metadata import build, validate_bindings
from micros_tooling.communication.protobuf import message_class

class ChannelMetadataTests(unittest.TestCase):
    def setUp(self):
        self.binding=make_device()['status']['channel_ports'][0]

    def test_published_port_round_trip_without_presentation(self):
        validate_bindings([self.binding])
        self.assertEqual(set(self.binding['port']), {'name','key','descriptor'})
        cls=message_class(self.binding['port']['descriptor'])
        self.assertEqual(cls.FromString(cls(value=7).SerializeToString()).value,7)

    def test_typed_reply_cursor_is_not_published_for_diagnostic_readers(self):
        service={'_commands':{'request_key':1,'response_key':2},
                 '_interface':{'ports':[{'name':'reply','key':2,'access':'publish'}]}}
        self.assertEqual(build(service), [])

    def test_rejects_ui_fields_duplicate_ports_and_invalid_bounds(self):
        for key,value in [('title','Plot'),('kind','waveform'),('series',[])]:
            bad=copy.deepcopy(self.binding);bad['port'][key]=value
            with self.assertRaises(ValueError): validate_bindings([bad])
        with self.assertRaises(ValueError):validate_bindings([self.binding,self.binding])
        for key in (0,33,True):
            bad=copy.deepcopy(self.binding);bad['port']['key']=key
            with self.assertRaises(ValueError):validate_bindings([bad])
        bad=copy.deepcopy(self.binding);bad['port']=[]
        with self.assertRaises(ValueError):validate_bindings([bad])

if __name__=='__main__':unittest.main()
