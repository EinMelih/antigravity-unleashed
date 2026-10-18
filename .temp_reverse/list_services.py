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

services = []
for b64 in descriptors:
    try:
        b64_padded = b64 + '=' * (-len(b64) % 4)
        raw = base64.b64decode(b64_padded)
        fd = FileDescriptorProto()
        fd.ParseFromString(raw)
        for s in fd.service:
            services.append({
                'proto': fd.name,
                'package': fd.package,
                'service': s.name,
                'full_name': f"{fd.package}.{s.name}" if fd.package else s.name,
                'methods': len(s.method),
                'method_names': [m.name for m in s.method]
            })
    except:
        pass

print(f"{'#':<3} | {'Service Full Name':<50} | {'Methods':<7} | {'Proto File'}")
print("-" * 110)
for i, s in enumerate(services, 1):
    print(f"{i:<3} | {s['full_name']:<50} | {s['methods']:<7} | {s['proto']}")

total_methods = sum(s['methods'] for s in services)
print("-" * 110)
print(f"Total: {len(services)} services, {total_methods} RPC methods")
