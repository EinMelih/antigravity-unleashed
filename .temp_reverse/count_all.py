import base64
import json
import sys
from google.protobuf.descriptor_pb2 import FileDescriptorProto

sys.stdout.reconfigure(encoding='utf-8')

with open(r'y:\Projects\antigravity-unleashed\.temp_reverse\main_bundle.js', 'r', encoding='utf-8', errors='ignore') as f:
    bundle = f.read()

descriptors = []
pos = 0
while True:
    idx = bundle.find('Ac("C', pos)
    if idx == -1:
        break
    start = idx + 4
    end = bundle.find('"', start)
    if end != -1:
        b64 = bundle[start:end]
        descriptors.append(b64)
    pos = idx + 5

proto_files = {}
all_services = []
total_messages = 0
total_enums = 0
total_methods = 0

for b64 in descriptors:
    try:
        b64_padded = b64 + '=' * (-len(b64) % 4)
        raw = base64.b64decode(b64_padded)
        fd = FileDescriptorProto()
        fd.ParseFromString(raw)
        if fd.name and (fd.name.endswith('.proto') or fd.package):
            proto_files[fd.name] = fd
            total_messages += len(fd.message_type)
            total_enums += len(fd.enum_type)
            for s in fd.service:
                all_services.append((fd.name, fd.package, s.name, len(s.method)))
                total_methods += len(s.method)
    except:
        pass

print("=== PROTOBUF INVENTORY SUMMARY ===")
print(f"Total Unique Proto Files: {len(proto_files)}")
print(f"Total Services: {len(all_services)}")
print(f"Total RPC Methods: {total_methods}")
print(f"Total Message Types: {total_messages}")
print(f"Total Enum Types: {total_enums}")

print("\nServices Breakdown:")
for fn, pkg, sname, count in sorted(all_services, key=lambda x: -x[3]):
    print(f"  {pkg}.{sname:<35} : {count:>3} methods  (in {fn})")
