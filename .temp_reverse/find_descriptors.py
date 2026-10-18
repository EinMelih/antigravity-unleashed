import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open(r'y:\Projects\antigravity-unleashed\.temp_reverse\main_bundle.js', 'r', encoding='utf-8', errors='ignore') as f:
    bundle = f.read()

# Let's search for calls to Ac( or fileDesc(
# Ac is the minified function for fileDesc!
print("Searching for Ac(\" patterns...")

# Find all matches of var \w+\s*=\s*Ac\(
matches = list(re.finditer(r'var\s+([A-Za-z0-9_$]+)\s*=\s*Ac\s*\(\s*"([^"]+)"\s*\)', bundle))
print(f"Found {len(matches)} Ac(\"...\") file descriptor calls!")

for m in matches:
    var_name = m.group(1)
    b64 = m.group(2)
    print(f"Variable '{var_name}': base64 length = {len(b64)}")

# Also let's search if there are other functions calling fileDesc or creating descriptors
other_matches = list(re.finditer(r'=\s*([A-Za-z0-9_$]+)\s*\(\s*"(C[A-Za-z0-9+/=]{50,})"\s*\)', bundle))
print(f"Found {len(other_matches)} large base64 calls starting with 'C' (proto tag 1: filename)!")
seen = set()
for m in other_matches:
    func_name = m.group(1)
    b64 = m.group(2)
    prefix = b64[:20]
    if prefix not in seen:
        seen.add(prefix)
        print(f"Function '{func_name}': b64 length = {len(b64)}, preview={b64[:40]}...")
