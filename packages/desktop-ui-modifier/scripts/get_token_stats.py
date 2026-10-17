import sqlite3
import sys
import json
from pathlib import Path

def parse_proto(data):
    pos = 0
    res = []
    while pos < len(data):
        try:
            header = 0
            shift = 0
            while True:
                b = data[pos]
                header |= (b & 0x7f) << shift
                pos += 1
                if not (b & 0x80): break
                shift += 7
            field_num = header >> 3
            wire_type = header & 0x07
            
            if wire_type == 0:
                val = 0
                shift = 0
                while True:
                    b = data[pos]
                    val |= (b & 0x7f) << shift
                    pos += 1
                    if not (b & 0x80): break
                    shift += 7
                res.append((field_num, "varint", val))
            elif wire_type == 2:
                length = 0
                shift = 0
                while True:
                    b = data[pos]
                    length |= (b & 0x7f) << shift
                    pos += 1
                    if not (b & 0x80): break
                    shift += 7
                val = data[pos:pos+length]
                pos += length
                res.append((field_num, "bytes", val))
            elif wire_type == 1:
                pos += 8
            elif wire_type == 5:
                pos += 4
            else:
                break
        except IndexError:
            break
    return res

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "missing_arg"}))
        return
        
    db_path = Path(sys.argv[1])
    if not db_path.exists():
        print(json.dumps({"error": "not_found"}))
        return
        
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT data FROM gen_metadata ORDER BY idx ASC").fetchall()
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return
        
    t_in = t_un = t_out = 0
    l_in = l_un = l_out = 0
    for row in rows:
        fields = parse_proto(row[0])
        for fn, wt, val in fields:
            if fn == 1:
                for sfn, swt, sval in parse_proto(val):
                    if sfn == 17:
                        for ssfn, sswt, ssval in parse_proto(sval):
                            if ssfn == 2:
                                f_map = {fn: val for fn, wt, val in parse_proto(ssval) if wt == "varint"}
                                uncached = f_map.get(2, 0)
                                out = f_map.get(3, 0)
                                inp = f_map.get(5, 0)
                                if inp == 0 and uncached > 0:
                                    inp = uncached
                                t_in += inp
                                t_un += uncached
                                t_out += out
                                l_in, l_un, l_out = inp, uncached, out
                                
    ratio = round((t_in - t_un) / t_in * 100, 1) if t_in > 0 else 0.0
    print(json.dumps({
        "totalInput": t_in,
        "totalUncached": t_un,
        "totalCached": t_in - t_un,
        "totalOutput": t_out,
        "latestInput": l_in,
        "latestUncached": l_un,
        "latestCached": l_in - l_un,
        "latestOutput": l_out,
        "cacheRatio": ratio
    }))

if __name__ == "__main__":
    main()
