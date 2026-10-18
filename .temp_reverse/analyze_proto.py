import sys

sys.stdout.reconfigure(encoding='utf-8')

with open(r'y:\Projects\antigravity-unleashed\.temp_reverse\main_bundle.js', 'r', encoding='utf-8', errors='ignore') as f:
    bundle = f.read()

# Find true .proto (not .prototype)
proto_files = set()
idx = 0
while True:
    pos = bundle.find('.proto', idx)
    if pos == -1:
        break
    if not bundle.startswith('.prototype', pos):
        # Found real .proto!
        start = max(0, pos - 50)
        end = min(len(bundle), pos + 20)
        snippet = bundle[start:end]
        print(f"Match at {pos}: {snippet.replace(chr(10), ' ')}")
    idx = pos + 6
