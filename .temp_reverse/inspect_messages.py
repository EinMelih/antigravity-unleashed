import base64
import sys
from google.protobuf.descriptor_pb2 import FileDescriptorProto, FieldDescriptorProto

sys.stdout.reconfigure(encoding='utf-8')

with open(r'y:\Projects\antigravity-unleashed\.temp_reverse\main_bundle.js', 'r', encoding='utf-8', errors='ignore') as f:
    bundle = f.read()

pos = 1563801
start = bundle.find('"', pos) + 1
end = bundle.find('"', start)
b64_w = bundle[start:end]
raw = base64.b64decode(b64_w + '=' * (-len(b64_w) % 4))
fd = FileDescriptorProto()
fd.ParseFromString(raw)

messages = {m.name: m for m in fd.message_type}

type_names = {
    FieldDescriptorProto.TYPE_DOUBLE: 'double',
    FieldDescriptorProto.TYPE_FLOAT: 'float',
    FieldDescriptorProto.TYPE_INT64: 'int64',
    FieldDescriptorProto.TYPE_UINT64: 'uint64',
    FieldDescriptorProto.TYPE_INT32: 'int32',
    FieldDescriptorProto.TYPE_FIXED64: 'fixed64',
    FieldDescriptorProto.TYPE_FIXED32: 'fixed32',
    FieldDescriptorProto.TYPE_BOOL: 'bool',
    FieldDescriptorProto.TYPE_STRING: 'string',
    FieldDescriptorProto.TYPE_GROUP: 'group',
    FieldDescriptorProto.TYPE_MESSAGE: 'message',
    FieldDescriptorProto.TYPE_BYTES: 'bytes',
    FieldDescriptorProto.TYPE_UINT32: 'uint32',
    FieldDescriptorProto.TYPE_ENUM: 'enum',
    FieldDescriptorProto.TYPE_SFIXED32: 'sfixed32',
    FieldDescriptorProto.TYPE_SFIXED64: 'sfixed64',
    FieldDescriptorProto.TYPE_SINT32: 'sint32',
    FieldDescriptorProto.TYPE_SINT64: 'sint64',
}

target_messages = [
    'StartCascadeRequest',
    'StartCascadeResponse',
    'SendUserCascadeMessageRequest',
    'SendUserCascadeMessageResponse',
    'StreamReactiveUpdatesRequest',
    'StreamReactiveUpdatesResponse',
    'StreamAgentStateUpdatesRequest',
    'StreamAgentStateUpdatesResponse',
    'AgentStatePageUpdateRequest',
    'AgentStatePageUpdateResponse',
    'GetCascadeTrajectoryRequest',
    'GetCascadeTrajectoryResponse',
    'RetrieveUserQuotaSummaryRequest',
    'RetrieveUserQuotaSummaryResponse',
    'GetAvailableModelsRequest',
    'GetAvailableModelsResponse'
]

for tname in target_messages:
    if tname in messages:
        m = messages[tname]
        print(f"\nmessage {m.name} {{")
        for f in m.field:
            t = type_names.get(f.type, f'type_{f.type}')
            if f.type_name:
                t = f.type_name.split('.')[-1]
            lbl = "repeated " if f.label == FieldDescriptorProto.LABEL_REPEATED else ""
            print(f"  {lbl}{t} {f.name} = {f.number};")
        print("}")
    else:
        print(f"\nMessage {tname} not found in language_server.proto, checking submessages...")
