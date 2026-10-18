import base64
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

all_services = []

for b64 in descriptors:
    try:
        b64_padded = b64 + '=' * (-len(b64) % 4)
        raw = base64.b64decode(b64_padded)
        fd = FileDescriptorProto()
        fd.ParseFromString(raw)
        for s in fd.service:
            all_services.append((fd.name, fd.package, s))
    except:
        pass

print(f"Total services found across all proto descriptors: {len(all_services)}")
for proto_file, pkg, s in all_services:
    print(f"\n=======================================================")
    print(f"Service: {pkg}.{s.name} in file '{proto_file}' ({len(s.method)} methods)")
    print(f"=======================================================")
    for m in s.method:
        cs = "stream " if m.client_streaming else ""
        ss = "stream " if m.server_streaming else ""
        print(f"  rpc {m.name} ({cs}{m.input_type}) returns ({ss}{m.output_type});")
