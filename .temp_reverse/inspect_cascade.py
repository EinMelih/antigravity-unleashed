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
raw = base64.b64decode(b64_w + '=' * (-len(b64_w) % 4))
fd = FileDescriptorProto()
fd.ParseFromString(raw)

# Map all messages by name
messages = {m.name: m for m in fd.message_type}

keywords = ['cascade', 'trajectory', 'step', 'turn', 'conversation', 'agentstate', 'chat']

print("=== Methods in LanguageServerService relating to Cascade / Trajectory / Agent ===")
s = fd.service[0]
cascade_methods = []
for m in s.method:
    name_lower = m.name.lower()
    if any(k in name_lower for k in keywords):
        cascade_methods.append(m)
        cs = "stream " if m.client_streaming else ""
        ss = "stream " if m.server_streaming else ""
        in_name = m.input_type.split('.')[-1]
        out_name = m.output_type.split('.')[-1]
        print(f"rpc {m.name:<35} ({cs}{in_name}) returns ({ss}{out_name});")

print(f"\nTotal cascade/trajectory related methods: {len(cascade_methods)}")
