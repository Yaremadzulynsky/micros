"""Executable contract sketch; no sockets, clocks, flash storage, or service ABI.

All ingress crosses serialized protobuf and explicit binding/kind admission.
Serialized records alone do not authenticate a sender; that is a transport and
deployment prerequisite. Checkpoint dictionaries model atomic durable records,
not an implementation of crash-safe persistence.
"""
from copy import deepcopy
from typing import NamedTuple
from wire_pb2 import Frame

MAX_PAYLOAD = 96
MAX_FRAME = 192
MAX_COUNTER = 2**64 - 1
TERMINAL = {Frame.Result.COMPLETED, Frame.Result.FAILED,
            Frame.Result.REJECTED, Frame.Result.INDETERMINATE}


class StateToken(NamedTuple):
    binding: int
    generation: int
    revision: int


def applied_token(record):
    if not record.HasField('applied'):
        return None
    ref = record.applied
    require(ref.binding > 0 and ref.generation > 0 and ref.revision > 0,
            'invalid applied reference')
    return StateToken(ref.binding, ref.generation, ref.revision)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def advance(counter):
    require(counter < MAX_COUNTER, 'counter exhausted; rebind explicitly')
    return counter + 1


def payload_bytes(payload):
    payload = bytes(payload)
    require(len(payload) <= MAX_PAYLOAD, 'payload exceeds bound')
    return payload


class Port:
    def __init__(self, binding=1, generation=1):
        require(0 < binding < 2**32 and 0 < generation <= MAX_COUNTER,
                'invalid binding identity')
        self.binding, self.generation = binding, generation

    def packet(self, kind, **fields):
        frame = Frame(protocol=1, binding=self.binding, generation=self.generation)
        getattr(frame, kind).CopyFrom(getattr(Frame, {
            'state': 'State', 'request': 'Request', 'result': 'Result',
            'event': 'Event'}[kind])(**fields))
        return frame.SerializeToString(deterministic=True)

    def decode(self, data, kind):
        require(len(data) <= MAX_FRAME, 'frame exceeds bound')
        frame = Frame.FromString(data)
        require(frame.protocol == 1 and frame.binding == self.binding and
                frame.generation == self.generation, 'unadmitted binding')
        require(frame.WhichOneof('record') == kind, 'wrong port kind')
        record = getattr(frame, kind)
        payload_bytes(record.payload)
        if kind == 'state':
            require(record.revision > 0 and record.refresh > 0, 'zero state identity')
            applied_token(record)
        else:
            require(record.sequence > 0, 'zero request/event identity')
        if kind == 'result':
            require(record.status == Frame.Result.ACCEPTED or record.status in TERMINAL,
                    'unknown result status')
        return record


class StateSource(Port):
    def __init__(self, **identity):
        super().__init__(**identity)
        self.value = None
        self.applied = None
        self.revision = self.refresh = 0

    def set(self, payload, applied=None):
        value = payload_bytes(payload)
        require(applied is None or isinstance(applied, StateToken) and
                0 < applied.binding < 2**32 and
                0 < applied.generation <= MAX_COUNTER and
                0 < applied.revision <= MAX_COUNTER, 'invalid applied token')
        if value != self.value or applied != self.applied:
            self.revision = advance(self.revision)
            self.value, self.applied = value, applied
        return self.revision

    def advertise(self):
        require(self.value is not None, 'state unavailable until initialized')
        self.refresh = advance(self.refresh)
        fields = dict(revision=self.revision, refresh=self.refresh, payload=self.value)
        if self.applied is not None:
            fields['applied'] = Frame.State.Applied(**self.applied._asdict())
        return self.packet('state', **fields)


class StateSink(Port):
    def __init__(self, **identity):
        super().__init__(**identity)
        self.value = None
        self.applied = None
        self.revision = self.refresh = 0
        self.last_observed_at = None

    def receive(self, data, now):
        record = self.decode(data, 'state')
        if record.refresh <= self.refresh:
            return False
        require(record.revision >= self.revision, 'revision regressed')
        applied = applied_token(record)
        require(record.revision != self.revision or
                (record.payload == self.value and applied == self.applied),
                'same revision changed content')
        changed = record.revision != self.revision
        self.value, self.revision, self.refresh = record.payload, record.revision, record.refresh
        self.applied = applied
        self.last_observed_at = now
        return changed

    def token(self):
        require(self.value is not None, 'no state to acknowledge')
        return StateToken(self.binding, self.generation, self.revision)

    def observation_stale(self, now, interval):
        # Receiver-local observation age ONLY, not end-to-end source freshness.
        return self.last_observed_at is None or now - self.last_observed_at >= interval


class ActionClient(Port):
    def __init__(self, **identity):
        super().__init__(**identity)
        self.sequence = 0
        self.request = None
        self.result = None

    def submit(self, payload):
        require(self.request is None or self.result is not None and
                self.result[0] in TERMINAL, 'one action already outstanding')
        value = payload_bytes(payload)
        self.sequence = advance(self.sequence)
        self.request, self.result = value, None
        return self.sequence  # Opaque ticket in a generated service API.

    def advertise(self):
        require(self.request is not None, 'no request')
        return self.packet('request', sequence=self.sequence, payload=self.request)

    def receive(self, data):
        record = self.decode(data, 'result')
        if record.sequence < self.sequence:
            return False
        require(self.request is not None and record.sequence == self.sequence,
                'unsolicited result')
        result = (record.status, record.payload)
        if self.result is not None and self.result[0] in TERMINAL:
            if record.status == Frame.Result.ACCEPTED:
                return False  # Delayed nonterminal status cannot undo completion.
            require(result == self.result, 'conflicting terminal result')
            return False
        changed = result != self.result
        self.result = result
        return changed


class ActionExecutor(Port):
    def __init__(self, **identity):
        super().__init__(**identity)
        self.sequence = 0
        self.request = None
        self.result = None

    def receive(self, data):
        record = self.decode(data, 'request')
        if record.sequence < self.sequence:
            return None
        if record.sequence == self.sequence:
            require(record.payload == self.request, 'same request ID changed content')
            return None
        require(record.sequence == self.sequence + 1, 'request sequence gap')
        require(self.result is None or self.result[0] in TERMINAL,
                'previous action unfinished')
        # A production runtime must atomically persist this BEFORE dispatch.
        self.sequence, self.request = record.sequence, record.payload
        self.result = (Frame.Result.ACCEPTED, b'')
        return (self.sequence, self.request)  # Dispatch once to application.

    def finish(self, ticket, status, payload=b''):
        require(ticket == self.sequence and self.result is not None and
                self.result[0] == Frame.Result.ACCEPTED, 'no matching active invocation')
        require(status in TERMINAL, 'completion must be terminal')
        self.result = (status, payload_bytes(payload))

    def advertise(self):
        require(self.result is not None, 'no result')
        return self.packet('result', sequence=self.sequence, status=self.result[0],
                           payload=self.result[1])

    def checkpoint(self):
        return deepcopy(vars(self))

    @classmethod
    def recover(cls, checkpoint):
        instance = cls(binding=checkpoint['binding'], generation=checkpoint['generation'])
        vars(instance).update(deepcopy(checkpoint))
        if instance.result is not None and instance.result[0] == Frame.Result.ACCEPTED:
            instance.result = (Frame.Result.INDETERMINATE, b'')
        return instance


class EventSource(Port):
    def __init__(self, **identity):
        super().__init__(**identity)
        self.sequence = 0

    def emit(self, payload):
        value = payload_bytes(payload)
        self.sequence = advance(self.sequence)
        return self.packet('event', sequence=self.sequence, payload=value)


class EventSink(Port):
    def __init__(self, **identity):
        super().__init__(**identity)
        self.sequence = 0

    def receive(self, data):
        record = self.decode(data, 'event')
        if record.sequence <= self.sequence:
            return None
        skipped = record.sequence - self.sequence - 1
        self.sequence = record.sequence
        return record.payload, skipped
