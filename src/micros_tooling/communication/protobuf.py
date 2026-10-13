"""Decode bounded, self-contained protobuf channel descriptors."""
import base64
from micros_tooling.storage.packages import require

def message_class(descriptor):
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    raw = base64.b64decode(descriptor, validate=True)
    require(len(raw) <= 8192, 'Channel descriptor exceeds 8 KiB')
    from google.protobuf.message import DecodeError
    try: file = descriptor_pb2.FileDescriptorProto.FromString(raw)
    except DecodeError as error: raise ValueError('Invalid channel protobuf descriptor') from error
    require(not file.dependency and len(file.message_type) == 1, 'Channel schema must be self-contained')
    pool = descriptor_pool.DescriptorPool()
    pool.Add(file)
    name = '.'.join(filter(None, [file.package, file.message_type[0].name]))
    return message_factory.GetMessageClass(pool.FindMessageTypeByName(name))
