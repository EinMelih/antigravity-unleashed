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

print(f"W base64 length: {len(b64_w)} characters ({len(b64_w)/1024:.2f} KB)")

# Add padding if needed
b64_padded = b64_w + '=' * (-len(b64_w) % 4)
raw = base64.b64decode(b64_padded)
print(f"Decoded binary proto size: {len(raw)} bytes ({len(raw)/1024:.2f} KB)")

fd = FileDescriptorProto()
fd.ParseFromString(raw)

print(f"Proto Name: {fd.name}")
print(f"Package: {fd.package}")
print(f"Total Messages: {len(fd.message_type)}")
print(f"Total Enums: {len(fd.enum_type)}")
print(f"Total Services: {len(fd.service)}")

for s in fd.service:
    print(f"\nService: {s.name} ({len(s.method)} methods)")
    for m in s.method:
        client_stream = "stream " if m.client_streaming else ""
        server_stream = "stream " if m.server_streaming else ""
        print(f"  rpc {m.name} ({client_stream}{m.input_type}) returns ({server_stream}{m.output_type})")

print("\nSample Messages (first 25):")
for m in fd.message_type[:25]:
    print(f"  message {m.name} ({len(m.field)} fields)")

print("\nSample Enums (first 10):")
for e in fd.enum_type[:10]:
    vals = [v.name for v in e.value[:5]]
    print(f"  enum {e.name}: {vals} ...")
