import base64
import re
import sys
from google.protobuf.descriptor_pb2 import FileDescriptorProto

sys.stdout.reconfigure(encoding='utf-8')

with open(r'y:\Projects\antigravity-unleashed\.temp_reverse\main_bundle.js', 'r', encoding='utf-8', errors='ignore') as f:
    bundle = f.read()

# Pattern for Ac("...") calls
# We find all occurrences of Ac("..." where the string inside starts with 'C' (proto tag 1: filename)
# We can search for Ac("C and find the matching closing quote
print("Scanning bundle for all Ac(\"C... patterns...")

descriptors = []
pos = 0
while True:
    idx = bundle.find('Ac("C', pos)
    if idx == -1:
        break
    start = idx + 4  # skip Ac("
    end = bundle.find('"', start)
    if end != -1:
        b64 = bundle[start:end]
        descriptors.append((idx, b64))
    pos = idx + 5

print(f"Found {len(descriptors)} candidate descriptor strings!")

decoded_protos = {}

for idx, b64 in descriptors:
    try:
        b64_padded = b64 + '=' * (-len(b64) % 4)
        raw = base64.b64decode(b64_padded)
        fd = FileDescriptorProto()
        fd.ParseFromString(raw)
        if fd.name and (fd.name.endswith('.proto') or fd.package):
            decoded_protos[fd.name] = fd
            print(f"Decoded: {fd.name} (package: {fd.package}) - Messages: {len(fd.message_type)}, Enums: {len(fd.enum_type)}, Services: {len(fd.service)}")
            for s in fd.service:
                print(f"  Service: {s.name} ({len(s.method)} methods)")
    except Exception as e:
        # Not a valid descriptor
        pass

print(f"\nTotal unique valid proto files decoded from bundle: {len(decoded_protos)}")
