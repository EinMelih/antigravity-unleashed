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

all_messages = {}
for b64 in descriptors:
    try:
        b64_padded = b64 + '=' * (-len(b64) % 4)
        raw = base64.b64decode(b64_padded)
        fd = FileDescriptorProto()
        fd.ParseFromString(raw)
        for m in fd.message_type:
            all_messages[f"{fd.package}.{m.name}"] = (fd.name, m)
            all_messages[m.name] = (fd.name, m)
    except:
        pass

targets = ['StreamReactiveUpdatesRequest', 'StreamReactiveUpdatesResponse', 'AgentStatePageUpdateRequest', 'AgentStatePageUpdateResponse', 'StreamAgentStateUpdatesRequest', 'StreamAgentStateUpdatesResponse']

for t in targets:
    if t in all_messages:
        proto_file, m = all_messages[t]
        print(f"\nFound {t} in '{proto_file}':")
        for f in m.field:
            print(f"  field #{f.number}: {f.name} (type: {f.type}, type_name: {f.type_name})")
    else:
        print(f"\n{t} NOT found in decoded protos!")
