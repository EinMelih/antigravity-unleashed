import sys
from google.protobuf.descriptor_pb2 import FileDescriptorProto, FieldDescriptorProto

sys.stdout.reconfigure(encoding='utf-8')

TYPE_MAP = {
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

def emit_proto(fd: FileDescriptorProto) -> str:
    lines = []
    lines.append('// Reconstructed by Antigravity Reverse Engineering Pipeline')
    syntax = fd.syntax if fd.syntax else 'proto3'
    lines.append(f'syntax = "{syntax}";')
    lines.append('')
    if fd.package:
        lines.append(f'package {fd.package};')
        lines.append('')

    for dep in fd.dependency:
        lines.append(f'import "{dep}";')
    if fd.dependency:
        lines.append('')

    for enum in fd.enum_type:
        lines.append(f'enum {enum.name} {{')
        for val in enum.value:
            lines.append(f'  {val.name} = {val.number};')
        lines.append('}')
        lines.append('')

    def emit_message(msg, indent=''):
        mlines = []
        mlines.append(f'{indent}message {msg.name} {{')
        for n_enum in msg.enum_type:
            mlines.append(f'{indent}  enum {n_enum.name} {{')
            for val in n_enum.value:
                mlines.append(f'{indent}    {val.name} = {val.number};')
            mlines.append(f'{indent}  }}')
            mlines.append('')
        for n_msg in msg.nested_type:
            if not n_msg.options.map_entry:
                mlines.extend(emit_message(n_msg, indent + '  '))

        for f in msg.field:
            lbl = ''
            if f.label == FieldDescriptorProto.LABEL_REPEATED:
                lbl = 'repeated '
            elif f.label == FieldDescriptorProto.LABEL_OPTIONAL and syntax == 'proto2':
                lbl = 'optional '
            elif f.proto3_optional:
                lbl = 'optional '

            type_str = TYPE_MAP.get(f.type, 'unknown')
            if f.type_name:
                type_str = f.type_name.lstrip('.')
                # if matches package, simplify or keep
                if fd.package and type_str.startswith(fd.package + '.'):
                    type_str = type_str[len(fd.package) + 1:]

            mlines.append(f'{indent}  {lbl}{type_str} {f.name} = {f.number};')
        mlines.append(f'{indent}}}')
        mlines.append('')
        return mlines

    for msg in fd.message_type:
        lines.extend(emit_message(msg))

    for svc in fd.service:
        lines.append(f'service {svc.name} {{')
        for m in svc.method:
            cs = "stream " if m.client_streaming else ""
            ss = "stream " if m.server_streaming else ""
            in_t = m.input_type.lstrip('.')
            if fd.package and in_t.startswith(fd.package + '.'):
                in_t = in_t[len(fd.package) + 1:]
            out_t = m.output_type.lstrip('.')
            if fd.package and out_t.startswith(fd.package + '.'):
                out_t = out_t[len(fd.package) + 1:]
            lines.append(f'  rpc {m.name} ({cs}{in_t}) returns ({ss}{out_t});')
        lines.append('}')
        lines.append('')

    return '\n'.join(lines)

# Test on host_bridge_pb.js
import base64
b64 = "ChFob3N0X2JyaWRnZS5wcm90bxISZXhhLmhvc3RfYnJpZGdlX3BiIhgKFkdldFVwZGF0ZVN0YXR1c1JlcXVlc3QiSwoXR2V0VXBkYXRlU3RhdHVzUmVzcG9uc2USMAoGc3RhdHVzGAEgASgLMiAuZXhhLmhvc3RfYnJpZGdlX3BiLlVwZGF0ZVN0YXR1cyJZCgxVcGRhdGVTdGF0dXMSFwoPY3VycmVudF92ZXJzaW9uGAEgASgJEhYKDmxhdGVzdF92ZXJzaW9uGAIgASgJEhgKEHVwZGF0ZV9hdmFpbGFibGUYAyABKAgiFAoSQXBwbHlVcGRhdGVSZXF1ZXN0IicKE0FwcGx5VXBkYXRlUmVzcG9uc2USEAoIYWNjZXB0ZWQYASABKAgy3wEKEUhvc3RCcmlkZ2VTZXJ2aWNlEmoKD0dldFVwZGF0ZVN0YXR1cxIqLmV4YS5ob3N0X2JyaWRnZV9wYi5HZXRVcGRhdGVTdGF0dXNSZXF1ZXN0GisuZXhhLmhvc3RfYnJpZGdlX3BiLkdldFVwZGF0ZVN0YXR1c1Jlc3BvbnNlEl4KC0FwcGx5VXBkYXRlEiYuZXhhLmhvc3RfYnJpZGdlX3BiLkFwcGx5VXBkYXRlUmVxdWVzdBonLmV4YS5ob3N0X2JyaWRnZV9wYi5BcHBseVVwZGF0ZVJlc3BvbnNlYgZwcm90bzM"
b64 += '=' * (-len(b64) % 4)
fd = FileDescriptorProto()
fd.ParseFromString(base64.b64decode(b64))

print("=== RECONSTRUCTED PROTO ===")
proto_text = emit_proto(fd)
print(proto_text)
