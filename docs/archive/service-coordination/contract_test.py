import random
import subprocess
import unittest
from google.protobuf.message import DecodeError
from wire_pb2 import Frame
from light_target_pb2 import LightTarget
from photo_request_pb2 import PhotoRequest
from photo_result_pb2 import PhotoResult
from model import (ActionClient, ActionExecutor, EventSink, EventSource,
                   StateSink, StateSource, MAX_COUNTER, Port)

CODEC = None


class StateTests(unittest.TestCase):
    def test_reported_state_confirms_exact_input_revision(self):
        desired, input_port = StateSource(binding=1), StateSink(binding=1)
        reported, observer = StateSource(binding=2), StateSink(binding=2)
        desired.set(b'50 percent')
        input_port.receive(desired.advertise(), 1)
        token = input_port.token()
        reported.set(b'actual 50 percent', applied=token)
        observer.receive(reported.advertise(), 2)
        self.assertEqual(observer.applied, token)
        self.assertEqual(observer.applied.binding, 1)
        desired.set(b'60 percent')
        input_port.receive(desired.advertise(), 3)
        self.assertEqual(reported.set(b'actual 50 percent', applied=input_port.token()), 2)
        observer.receive(reported.advertise(), 4)
        self.assertNotEqual(observer.applied, token)

    def test_lost_change_repaired_by_next_advertisement(self):
        source, sink = StateSource(), StateSink()
        source.set(LightTarget(brightness_percent=50).SerializeToString())
        source.advertise()  # Dropped.
        self.assertTrue(sink.receive(source.advertise(), now=1))
        self.assertEqual(LightTarget.FromString(sink.value).brightness_percent, 50)

    def test_refresh_does_not_repeat_application_change(self):
        source, sink = StateSource(), StateSink()
        source.set(b'value')
        first = source.advertise()
        sink.receive(first, 1)
        self.assertEqual(source.set(b'value'), 1)
        self.assertFalse(sink.receive(source.advertise(), 2))
        self.assertFalse(sink.observation_stale(3, 2))
        sink.receive(first, 3)  # Replay cannot refresh receiver observation.
        self.assertTrue(sink.observation_stale(4, 2))

    def test_reordering_cannot_undo_new_state(self):
        source, sink = StateSource(), StateSink()
        source.set(b'old')
        old = source.advertise()
        source.set(b'new')
        sink.receive(source.advertise(), 1)
        self.assertFalse(sink.receive(old, 2))
        self.assertEqual(sink.value, b'new')

    def test_empty_snapshot_is_available(self):
        source, sink = StateSource(), StateSink()
        with self.assertRaises(ValueError):
            source.advertise()
        self.assertTrue(sink.observation_stale(1, 10))
        source.set(b'')  # A protobuf containing all default values is valid.
        sink.receive(source.advertise(), 1)
        self.assertEqual(sink.value, b'')

    def test_conflicting_revision_rejected(self):
        sink = StateSink()
        sink.receive(Port().packet('state', revision=1, refresh=1, payload=b'a'), 1)
        with self.assertRaises(ValueError):
            sink.receive(Port().packet('state', revision=1, refresh=2, payload=b'b'), 2)

    def test_arbitrary_loss_then_recovery_converges(self):
        rng = random.Random(42)
        source, sink = StateSource(), StateSink()
        packets = []
        for number in range(100):
            source.set(bytes([number]))
            packets.append(source.advertise())
        rng.shuffle(packets)
        for packet in packets:
            if rng.random() > 0.6:
                sink.receive(packet, 1)
        sink.receive(source.advertise(), 2)
        self.assertEqual(sink.value, bytes([99]))


class ActionTests(unittest.TestCase):
    def pair(self):
        client, executor = ActionClient(), ActionExecutor()
        client.submit(PhotoRequest(exposure_us=100).SerializeToString())
        return client, executor

    def test_lost_request_and_result_recover_without_second_execution(self):
        client, executor = self.pair()
        client.advertise()  # Lost request.
        ticket, payload = executor.receive(client.advertise())
        self.assertEqual(PhotoRequest.FromString(payload).exposure_us, 100)
        executor.finish(ticket, Frame.Result.COMPLETED,
                        PhotoResult(photo_id=123).SerializeToString())
        executor.advertise()  # Lost completion.
        self.assertIsNone(executor.receive(client.advertise()))
        client.receive(executor.advertise())
        self.assertEqual(PhotoResult.FromString(client.result[1]).photo_id, 123)

    def test_accepted_does_not_allow_next_request(self):
        client, executor = self.pair()
        executor.receive(client.advertise())
        client.receive(executor.advertise())
        with self.assertRaises(ValueError):
            client.submit(b'next')

    def test_terminal_result_cannot_regress(self):
        client, executor = self.pair()
        ticket, _ = executor.receive(client.advertise())
        accepted = executor.advertise()
        executor.finish(ticket, Frame.Result.FAILED, b'error')
        client.receive(executor.advertise())
        self.assertFalse(client.receive(accepted))
        self.assertEqual(client.result[0], Frame.Result.FAILED)

    def test_counter_jump_is_not_interpreted_as_missing_actions(self):
        with self.assertRaises(ValueError):
            ActionExecutor().receive(Port().packet('request', sequence=3, payload=b'photo'))

    def test_reusing_id_with_different_arguments_rejected(self):
        client, executor = self.pair()
        executor.receive(client.advertise())
        with self.assertRaises(ValueError):
            executor.receive(Port().packet('request', sequence=1, payload=b'different'))

    def test_old_requests_do_not_execute_after_next_request(self):
        client, executor = self.pair()
        old = client.advertise()
        ticket, _ = executor.receive(old)
        executor.finish(ticket, Frame.Result.COMPLETED)
        client.receive(executor.advertise())
        client.submit(b'next')
        self.assertEqual(executor.receive(client.advertise()), (2, b'next'))
        self.assertIsNone(executor.receive(old))

    def test_interrupted_action_becomes_indeterminate(self):
        client, executor = self.pair()
        executor.receive(client.advertise())
        recovered = ActionExecutor.recover(executor.checkpoint())
        self.assertIsNone(recovered.receive(client.advertise()))
        client.receive(recovered.advertise())
        self.assertEqual(client.result[0], Frame.Result.INDETERMINATE)

    def test_completed_action_survives_modeled_checkpoint(self):
        client, executor = self.pair()
        ticket, _ = executor.receive(client.advertise())
        executor.finish(ticket, Frame.Result.COMPLETED, b'photo-ref')
        recovered = ActionExecutor.recover(executor.checkpoint())
        self.assertIsNone(recovered.receive(client.advertise()))
        client.receive(recovered.advertise())
        self.assertEqual(client.result, (Frame.Result.COMPLETED, b'photo-ref'))

    def test_stale_completion_ticket_cannot_complete_next_action(self):
        client, executor = self.pair()
        ticket, _ = executor.receive(client.advertise())
        executor.finish(ticket, Frame.Result.COMPLETED)
        client.receive(executor.advertise())
        client.submit(b'next')
        executor.receive(client.advertise())
        with self.assertRaises(ValueError):
            executor.finish(ticket, Frame.Result.COMPLETED)


class AdmissionTests(unittest.TestCase):
    def test_binding_and_generation_are_explicitly_admitted(self):
        for source in (StateSource(binding=2), StateSource(generation=2)):
            source.set(b'value')
            with self.assertRaises(ValueError):
                StateSink().receive(source.advertise(), 1)

    def test_kind_is_not_inferred_from_protobuf_payload(self):
        source = EventSource()
        with self.assertRaises(ValueError):
            StateSink().receive(source.emit(b'same bytes'), 1)

    def test_zero_identity_unknown_status_and_missing_record_rejected(self):
        executor = ActionExecutor()
        for data in (Frame(protocol=1, binding=1, generation=1).SerializeToString(),
                     Port().packet('request', sequence=0)):
            with self.assertRaises(ValueError):
                executor.receive(data)
        with self.assertRaises(ValueError):
            ActionClient().receive(Port().packet('result', sequence=1, status=99))

    def test_payload_and_packet_bounds(self):
        with self.assertRaises(ValueError):
            StateSource().set(b'x' * 97)
        with self.assertRaises(ValueError):
            StateSink().receive(Port().packet('state', revision=1, refresh=1,
                                             payload=b'x' * 97), 1)
        with self.assertRaises(ValueError):
            StateSink().receive(b'x' * 193, 1)
        with self.assertRaises(DecodeError):
            StateSink().receive(b'\x80', 1)

    def test_counter_exhaustion_does_not_wrap(self):
        source = StateSource()
        source.revision = MAX_COUNTER
        with self.assertRaises(ValueError):
            source.set(b'value')

    def test_event_gap_and_duplicate_handling(self):
        source, sink = EventSource(), EventSink()
        source.emit(b'lost')
        packet = source.emit(b'new')
        self.assertEqual(sink.receive(packet), (b'new', 1))
        self.assertIsNone(sink.receive(packet))

    def test_native_nanopb_roundtrip_all_record_kinds(self):
        port = Port(binding=2**32-1, generation=MAX_COUNTER)
        for kind, fields in (
            ('state', dict(revision=MAX_COUNTER, refresh=MAX_COUNTER,
                           applied=Frame.State.Applied(binding=2**32-1,
                                                       generation=MAX_COUNTER,
                                                       revision=MAX_COUNTER))),
            ('request', dict(sequence=MAX_COUNTER)),
            ('result', dict(sequence=MAX_COUNTER, status=Frame.Result.INDETERMINATE)),
            ('event', dict(sequence=MAX_COUNTER))):
            packet = port.packet(kind, payload=b'x' * 96, **fields)
            result = subprocess.run([CODEC], input=packet, capture_output=True, check=True)
            self.assertEqual(Frame.FromString(result.stdout), Frame.FromString(packet))
        oversized = port.packet('request', sequence=1, payload=b'x' * 97)
        self.assertNotEqual(subprocess.run([CODEC], input=oversized,
                                          capture_output=True).returncode, 0)
