import sys

sys.stdout.reconfigure(encoding='utf-8')

with open(r'y:\Projects\antigravity-unleashed\.temp_reverse\main_bundle.js', 'r', encoding='utf-8', errors='ignore') as f:
    bundle = f.read()

pos = 9462612 # where O2a, F2a, czc are called
print("=== Transport and Client construction ===")
print(bundle[pos-500:pos+1500])

# Find O2a definition
m = bundle.rfind('function O2a', 0, pos)
if m == -1:
    m = bundle.rfind('var O2a=', 0, pos)
print(f"\nO2a definition at {m}:")
print(bundle[m:m+800])

# Find F2a definition (WebSocket transport)
m2 = bundle.rfind('var F2a=', 0, pos)
if m2 == -1:
    m2 = bundle.rfind('function F2a', 0, pos)
print(f"\nF2a definition at {m2}:")
print(bundle[m2:m2+800])
