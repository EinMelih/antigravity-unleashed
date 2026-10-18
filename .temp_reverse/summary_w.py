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

print(f"=== {fd.name} ===")
print(f"Package: {fd.package}")
print(f"Messages count: {len(fd.message_type)}")
print(f"Enums count: {len(fd.enum_type)}")
print(f"Services count: {len(fd.service)}")
for s in fd.service:
    print(f"Service '{s.name}': {len(s.method)} methods")
