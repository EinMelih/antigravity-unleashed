import base64
import sys
from google.protobuf.descriptor_pb2 import FileDescriptorProto

sys.stdout.reconfigure(encoding='utf-8')

with open(r'y:\Projects\antigravity-unleashed\.temp_reverse\main_bundle.js', 'r', encoding='utf-8', errors='ignore') as f:
    bundle = f.read()

pos = 1563801
start = bundle.find('"', pos) + 1
end = bundle.find('"', start)
b64_w = bundle[start:end]

b64_padded = b64_w + '=' * (-len(b64_w) % 4)
raw = base64.b64decode(b64_padded)

fd = FileDescriptorProto()
fd.ParseFromString(raw)

print(f"File Name: {fd.name}")
print(f"Package: {fd.package}")
print(f"Total Messages in {fd.name}: {len(fd.message_type)}")
print(f"Total Enums in {fd.name}: {len(fd.enum_type)}")
print(f"Total Services in {fd.name}: {len(fd.service)}")

total_methods = 0
for s in fd.service:
    print(f"\nService: {s.name} ({len(s.method)} methods)")
    total_methods += len(s.method)
    for m in s.method:
        cs = "stream " if m.client_streaming else ""
        ss = "stream " if m.server_streaming else ""
        print(f"    rpc {m.name} ({cs}{m.input_type}) returns ({ss}{m.output_type});")

print(f"\nTotal RPC Methods in this service alone: {total_methods}")
