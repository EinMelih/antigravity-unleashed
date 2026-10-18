from pathlib import Path
import base64
import os
import sys
import json
from google.protobuf.descriptor_pb2 import (
    FileDescriptorProto,
    DescriptorProto,
    FieldDescriptorProto,
    EnumDescriptorProto,
    ServiceDescriptorProto,
)

sys.stdout.reconfigure(encoding='utf-8')

TYPE_MAP = {
    FieldDescriptorProto.TYPE_DOUBLE: 'double',
    FieldDescriptorProto.TYPE_FLOAT: 'float',
    FieldDescriptorProto.TYPE_INT64: 'int64',
    FieldDescriptorProto.TYPE_UINT64: 'uint64',
    FieldDescriptorProto.TYPE_INT32: 'int32',
    FieldDescriptorProto.TYPE_FIXED64: 'fixed64',
    FieldDescriptorProto.TYPE_FIXED32: 'fixed32',
    FieldDescriptorProto.TYPE_BOOL: 'bool',
    FieldDescriptorProto.TYPE_STRING: 'string',
    FieldDescriptorProto.TYPE_GROUP: 'group',
    FieldDescriptorProto.TYPE_MESSAGE: 'message',
    FieldDescriptorProto.TYPE_BYTES: 'bytes',
    FieldDescriptorProto.TYPE_UINT32: 'uint32',
    FieldDescriptorProto.TYPE_ENUM: 'enum',
    FieldDescriptorProto.TYPE_SFIXED32: 'sfixed32',
    FieldDescriptorProto.TYPE_SFIXED64: 'sfixed64',
    FieldDescriptorProto.TYPE_SINT32: 'sint32',
    FieldDescriptorProto.TYPE_SINT64: 'sint64',
}

def clean_type_name(t_name: str) -> str:
    if not t_name:
        return 'unknown'
    return t_name.lstrip('.')

def format_type(field: FieldDescriptorProto, map_entries: dict) -> str:
    if field.type == FieldDescriptorProto.TYPE_MESSAGE and field.type_name in map_entries:
        key_t, val_t = map_entries[field.type_name]
        return f"map<{key_t}, {val_t}>"
    if field.type in (FieldDescriptorProto.TYPE_MESSAGE, FieldDescriptorProto.TYPE_ENUM):
        return clean_type_name(field.type_name)
    return TYPE_MAP.get(field.type, 'unknown')

def format_reserved_ranges(ranges) -> list:
    if not ranges:
        return []
    sorted_r = sorted(ranges, key=lambda r: r.start)
    merged = []
    for r in sorted_r:
        start = r.start
        end = r.end - 1
        if not merged:
            merged.append([start, end])
        else:
            prev = merged[-1]
            if start <= prev[1] + 1:
                prev[1] = max(prev[1], end)
            else:
                merged.append([start, end])
    
    parts = []
    for start, end in merged:
        if start == end:
            parts.append(str(start))
        else:
            parts.append(f"{start} to {end}")
    return parts

def build_symbol_table(protos: dict) -> dict:
    symbols = {}
    for name, fd in protos.items():
        pkg = fd.package
        def add_enum(e, parent=''):
            full = f"{parent}.{e.name}" if parent else (f".{pkg}.{e.name}" if pkg else f".{e.name}")
            symbols[full] = name
            symbols[full.lstrip('.')] = name
        def add_msg(m, parent=''):
            full = f"{parent}.{m.name}" if parent else (f".{pkg}.{m.name}" if pkg else f".{m.name}")
            symbols[full] = name
            symbols[full.lstrip('.')] = name
            for ne in m.enum_type:
                add_enum(ne, full)
            for nm in m.nested_type:
                if not nm.options.map_entry:
                    add_msg(nm, full)

        for e in fd.enum_type:
            add_enum(e)
        for m in fd.message_type:
            add_msg(m)
    return symbols

def emit_proto(fd: FileDescriptorProto, symbols: dict) -> str:
    lines = []
    lines.append('// Reconstructed by Antigravity Unleashed Protobuf Reverse Engineering Pipeline')
    lines.append('// Source: Antigravity IDE v2.24.0 (Electron Client / Embedded Language Server)')
    lines.append(f'// Original descriptor path: {fd.name}')
    lines.append('')

    syntax = 'proto3'
    if fd.syntax == 'proto2':
        syntax = 'proto2'
    lines.append(f'syntax = "{syntax}";')
    lines.append('')

    if fd.package:
        lines.append(f'package {fd.package};')
        lines.append('')

    # Calculate complete imports including referenced symbols
    all_deps = set(fd.dependency)
    def check_ref(t_name):
        if not t_name:
            return
        cleaned = t_name if t_name.startswith('.') else f".{t_name}"
        if cleaned in symbols:
            target_file = symbols[cleaned]
            if target_file != fd.name:
                all_deps.add(target_file)

    def scan_msg_refs(m: DescriptorProto):
        for f in m.field:
            if f.type_name:
                check_ref(f.type_name)
        for ext in m.extension:
            if ext.extendee:
                check_ref(ext.extendee)
            if ext.type_name:
                check_ref(ext.type_name)
        for nm in m.nested_type:
            scan_msg_refs(nm)

    for m in fd.message_type:
        scan_msg_refs(m)
    for ext in fd.extension:
        if ext.extendee:
            check_ref(ext.extendee)
        if ext.type_name:
            check_ref(ext.type_name)
    for svc in fd.service:
        for m in svc.method:
            check_ref(m.input_type)
            check_ref(m.output_type)

    if all_deps:
        # Sort imports: google/protobuf first, then alphabetical
        def dep_sort_key(d):
            if d.startswith('google/protobuf/'):
                return (0, d)
            if d.startswith('google/'):
                return (1, d)
            return (2, d)
        for dep in sorted(all_deps, key=dep_sort_key):
            lines.append(f'import "{dep}";')
        lines.append('')

    # File-level extensions
    if fd.extension:
        exts_by_target = {}
        for ext in fd.extension:
            exts_by_target.setdefault(ext.extendee, []).append(ext)
        for target, exts in exts_by_target.items():
            lines.append(f'extend {clean_type_name(target)} {{')
            for ext in exts:
                t_str = format_type(ext, {})
                lbl = 'optional ' if syntax == 'proto2' else ''
                lines.append(f'  {lbl}{t_str} {ext.name} = {ext.number};')
            lines.append('}')
            lines.append('')

    # File-level enums
    for enum in fd.enum_type:
        lines.append(f'enum {enum.name} {{')
        if enum.options.allow_alias:
            lines.append('  option allow_alias = true;')
        for val in enum.value:
            lines.append(f'  {val.name} = {val.number};')
        if enum.reserved_range:
            rr = format_reserved_ranges(enum.reserved_range)
            if rr:
                lines.append(f'  reserved {", ".join(rr)};')
        if enum.reserved_name:
            rn = [f'"{n}"' for n in enum.reserved_name]
            lines.append(f'  reserved {", ".join(rn)};')
        lines.append('}')
        lines.append('')

    # Message emitter
    def emit_message(msg: DescriptorProto, indent=''):
        mlines = []
        mlines.append(f'{indent}message {msg.name} {{')

        # Detect map entries
        map_entries = {}
        for n_msg in msg.nested_type:
            if n_msg.options.map_entry:
                k_f = next((f for f in n_msg.field if f.number == 1), None)
                v_f = next((f for f in n_msg.field if f.number == 2), None)
                k_t = format_type(k_f, {}) if k_f else 'string'
                v_t = format_type(v_f, {}) if v_f else 'string'
                full_name = f".{fd.package}.{msg.name}.{n_msg.name}" if fd.package else f".{msg.name}.{n_msg.name}"
                map_entries[full_name] = (k_t, v_t)
                map_entries[f"{msg.name}.{n_msg.name}"] = (k_t, v_t)
                map_entries[n_msg.name] = (k_t, v_t)

        # Nested Enums
        for n_enum in msg.enum_type:
            mlines.append(f'{indent}  enum {n_enum.name} {{')
            if n_enum.options.allow_alias:
                mlines.append(f'{indent}    option allow_alias = true;')
            for val in n_enum.value:
                mlines.append(f'{indent}    {val.name} = {val.number};')
            if n_enum.reserved_range:
                rr = format_reserved_ranges(n_enum.reserved_range)
                if rr:
                    mlines.append(f'{indent}    reserved {", ".join(rr)};')
            if n_enum.reserved_name:
                rn = [f'"{n}"' for n in n_enum.reserved_name]
                mlines.append(f'{indent}    reserved {", ".join(rn)};')
            mlines.append(f'{indent}  }}')
            mlines.append('')

        # Nested Messages (excluding map entries)
        for n_msg in msg.nested_type:
            if not n_msg.options.map_entry:
                mlines.extend(emit_message(n_msg, indent + '  '))

        # Extensions inside message
        if msg.extension:
            exts_by_target = {}
            for ext in msg.extension:
                exts_by_target.setdefault(ext.extendee, []).append(ext)
            for target, exts in exts_by_target.items():
                mlines.append(f'{indent}  extend {clean_type_name(target)} {{')
                for ext in exts:
                    t_str = format_type(ext, map_entries)
                    lbl = 'optional ' if syntax == 'proto2' else ''
                    mlines.append(f'{indent}    {lbl}{t_str} {ext.name} = {ext.number};')
                mlines.append(f'{indent}  }}')
                mlines.append('')

        # Group oneofs and regular fields
        oneof_fields = {}
        for f in msg.field:
            if f.HasField('oneof_index') and not getattr(f, 'proto3_optional', False):
                oneof_fields.setdefault(f.oneof_index, []).append(f)

        handled_fields = set()
        for f in msg.field:
            if f.number in handled_fields:
                continue

            if f.HasField('oneof_index') and not getattr(f, 'proto3_optional', False):
                o_idx = f.oneof_index
                o_name = msg.oneof_decl[o_idx].name if o_idx < len(msg.oneof_decl) else f'choice_{o_idx}'
                o_members = oneof_fields.get(o_idx, [f])
                mlines.append(f'{indent}  oneof {o_name} {{')
                for of in o_members:
                    t_str = format_type(of, map_entries)
                    mlines.append(f'{indent}    {t_str} {of.name} = {of.number};')
                    handled_fields.add(of.number)
                mlines.append(f'{indent}  }}')
            else:
                t_str = format_type(f, map_entries)
                is_map = t_str.startswith('map<')
                prefix = ''
                if is_map:
                    prefix = ''
                elif f.label == FieldDescriptorProto.LABEL_REPEATED:
                    prefix = 'repeated '
                elif getattr(f, 'proto3_optional', False) or (f.label == FieldDescriptorProto.LABEL_OPTIONAL and syntax == 'proto2'):
                    prefix = 'optional '
                elif f.label == FieldDescriptorProto.LABEL_REQUIRED:
                    prefix = 'required '

                mlines.append(f'{indent}  {prefix}{t_str} {f.name} = {f.number};')
                handled_fields.add(f.number)

        # Reserved ranges and names
        if msg.reserved_range:
            rr = format_reserved_ranges(msg.reserved_range)
            if rr:
                mlines.append(f'{indent}  reserved {", ".join(rr)};')
        if msg.reserved_name:
            rn = [f'"{n}"' for n in msg.reserved_name]
            mlines.append(f'{indent}  reserved {", ".join(rn)};')

        mlines.append(f'{indent}}}')
        mlines.append('')
        return mlines

    # Top-level messages
    for msg in fd.message_type:
        lines.extend(emit_message(msg))

    # Services
    for svc in fd.service:
        lines.append(f'service {svc.name} {{')
        for m in svc.method:
            cs = "stream " if m.client_streaming else ""
            ss = "stream " if m.server_streaming else ""
            in_t = clean_type_name(m.input_type)
            out_t = clean_type_name(m.output_type)
            lines.append(f'  rpc {m.name} ({cs}{in_t}) returns ({ss}{out_t});')
        lines.append('}')
        lines.append('')

    return '\n'.join(lines)

def extract_proto_schemas(bundle_path=None, proto_dir=None, catalog_path=None):
    base_dir = Path(__file__).resolve().parent.parent
    if proto_dir is None:
        proto_dir = str(base_dir / 'proto')
    if catalog_path is None:
        catalog_path = str(base_dir / 'catalog' / 'rpc_schema.json')

    if bundle_path is None:
        candidates = [
            base_dir / 'extracted' / 'frontend' / 'main_bundle.js',
            base_dir.parent.parent / '.temp_reverse' / 'main_bundle.js',
            r'y:\Projects\antigravity-unleashed\.temp_reverse\main_bundle.js'
        ]
        for c in candidates:
            if os.path.exists(c):
                bundle_path = str(c)
                break

    if not bundle_path or not os.path.exists(bundle_path):
        raise FileNotFoundError(f'Could not find main_bundle.js. Candidates checked: {candidates}')

    print(f'Loading descriptors from bundle: {bundle_path}')
    with open(bundle_path, 'r', encoding='utf-8', errors='ignore') as f:
        bundle = f.read()

    pos = 0
    protos = {}
    while True:
        idx = bundle.find('Ac("C', pos)
        if idx == -1:
            break
        start = idx + 4
        end = bundle.find('"', start)
        if end != -1:
            b64 = bundle[start:end]
            try:
                b64_padded = b64 + '=' * (-len(b64) % 4)
                raw = base64.b64decode(b64_padded)
                fd = FileDescriptorProto()
                fd.ParseFromString(raw)
                if fd.name:
                    protos[fd.name] = fd
            except:
                pass
        pos = idx + 5

    print(f"Decoded {len(protos)} unique proto descriptors from bundle.")

    # Build symbol table
    symbols = build_symbol_table(protos)
    print(f"Indexed {len(symbols)} symbol locations across all descriptors.")

    proto_base = str(proto_dir)
    
    written_files = 0
    all_services = []
    all_methods = []
    all_messages = {}
    all_enums = {}

    for name, fd in protos.items():
        proto_code = emit_proto(fd, symbols)
        target_path = os.path.join(proto_base, name.replace('/', os.sep))
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'w', encoding='utf-8') as pf:
            pf.write(proto_code)
        written_files += 1

        for svc in fd.service:
            svc_full = f"{fd.package}.{svc.name}" if fd.package else svc.name
            svc_dict = {
                "name": svc.name,
                "package": fd.package,
                "full_name": svc_full,
                "proto_file": fd.name,
                "method_count": len(svc.method),
                "methods": []
            }
            for m in svc.method:
                m_path = f"/{svc_full}/{m.name}"
                in_t = clean_type_name(m.input_type)
                out_t = clean_type_name(m.output_type)
                m_info = {
                    "service": svc_full,
                    "name": m.name,
                    "path": m_path,
                    "request_type": in_t,
                    "response_type": out_t,
                    "client_streaming": bool(m.client_streaming),
                    "server_streaming": bool(m.server_streaming)
                }
                svc_dict["methods"].append(m_info)
                all_methods.append(m_info)
            all_services.append(svc_dict)

        def extract_msg(msg: DescriptorProto, parent_prefix=''):
            full_name = f"{parent_prefix}.{msg.name}" if parent_prefix else (f"{fd.package}.{msg.name}" if fd.package else msg.name)
            fields_list = []
            for f in msg.field:
                fields_list.append({
                    "number": f.number,
                    "name": f.name,
                    "type": TYPE_MAP.get(f.type, 'unknown'),
                    "type_name": clean_type_name(f.type_name) if f.type_name else None,
                    "label": "repeated" if f.label == FieldDescriptorProto.LABEL_REPEATED else ("optional" if getattr(f, 'proto3_optional', False) else "singular"),
                    "oneof_index": f.oneof_index if f.HasField('oneof_index') and not getattr(f, 'proto3_optional', False) else None
                })
            all_messages[full_name] = {
                "name": msg.name,
                "full_name": full_name,
                "package": fd.package,
                "proto_file": fd.name,
                "fields": fields_list,
                "nested_types": [n.name for n in msg.nested_type if not n.options.map_entry],
                "nested_enums": [e.name for e in msg.enum_type]
            }
            for n_msg in msg.nested_type:
                if not n_msg.options.map_entry:
                    extract_msg(n_msg, full_name)
            for n_enum in msg.enum_type:
                enum_full = f"{full_name}.{n_enum.name}"
                all_enums[enum_full] = {
                    "name": n_enum.name,
                    "full_name": enum_full,
                    "package": fd.package,
                    "proto_file": fd.name,
                    "values": [{"name": v.name, "number": v.number} for v in n_enum.value]
                }

        for msg in fd.message_type:
            extract_msg(msg)

        for enum in fd.enum_type:
            enum_full = f"{fd.package}.{enum.name}" if fd.package else enum.name
            all_enums[enum_full] = {
                "name": enum.name,
                "full_name": enum_full,
                "package": fd.package,
                "proto_file": fd.name,
                "values": [{"name": v.name, "number": v.number} for v in enum.value]
            }

    # Top-level mirrors
    major_mappings = {
        'language_server.proto': 'third_party/jetski/language_server_pb/language_server.proto',
        'cortex.proto': 'third_party/jetski/cortex_pb/cortex.proto',
        'trajectory.proto': 'third_party/gemini_coder/proto/trajectory.proto',
        'api_server.proto': 'third_party/jetski/api_server_pb/api_server.proto',
        'extension_server.proto': 'third_party/jetski/extension_server_pb/extension_server.proto',
        'jetski_service.proto': 'google/internal/cloud/code/v1internal/jetski_service.proto',
        'host_bridge.proto': 'third_party/jetski/host_bridge_pb/host_bridge.proto',
        'chat.proto': 'third_party/jetski/chat_pb/chat.proto',
        'codeium_common.proto': 'third_party/jetski/codeium_common_pb/codeium_common.proto',
        'index.proto': 'third_party/jetski/index_pb/index.proto',
        'reactive_component.proto': 'third_party/jetski/reactive_component_pb/reactive_component.proto',
        'jetski_cortex.proto': 'third_party/jetski/jetski_cortex_pb/jetski_cortex.proto',
    }

    for top_name, src_rel in major_mappings.items():
        src_file = os.path.join(proto_base, src_rel.replace('/', os.sep))
        dst_file = os.path.join(proto_base, top_name)
        if os.path.exists(src_file):
            with open(src_file, 'r', encoding='utf-8') as sf:
                content = sf.read()
            with open(dst_file, 'w', encoding='utf-8') as df:
                df.write(content)

    # Save catalog
    catalog_path = str(catalog_path)
    catalog_data = {
        "version": "1.0.0",
        "title": "Antigravity Connect & gRPC-Web Service Schema Catalog",
        "description": "Complete specification of all 16 Connect/gRPC-Web services, 650 RPC methods, 2,831 Protobuf messages, and 306 enums reverse-engineered from Google Antigravity v2.24.0.",
        "metadata": {
            "total_proto_files": written_files,
            "total_services": len(all_services),
            "total_methods": len(all_methods),
            "total_message_types": len(all_messages),
            "total_enums": len(all_enums)
        },
        "services": sorted(all_services, key=lambda s: -s["method_count"]),
        "methods": sorted(all_methods, key=lambda m: m["path"]),
        "message_types": all_messages,
        "enums": all_enums
    }

    with open(catalog_path, 'w', encoding='utf-8') as jf:
        json.dump(catalog_data, jf, indent=2, ensure_ascii=False)

    print("\n=== GENERATION WITH COMPLETE DEPENDENCY GRAPH COMPLETE ===")
    print(f"Total .proto files written: {written_files}")
    print(f"Total services cataloged: {len(all_services)}")
    print(f"Total methods cataloged: {len(all_methods)}")
    print(f"Total messages cataloged: {len(all_messages)}")
    print(f"Total enums cataloged: {len(all_enums)}")
    print(f"Catalog saved to: {catalog_path}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract Protobuf definitions and Connect service catalog.")
    parser.add_argument("--bundle-path", "-b", default=None, help="Path to main_bundle.js")
    parser.add_argument("--proto-dir", "-p", default=None, help="Output directory for reconstructed .proto files")
    parser.add_argument("--catalog-path", "-c", default=None, help="Output path for rpc_schema.json")
    args = parser.parse_args()
    extract_proto_schemas(args.bundle_path, args.proto_dir, args.catalog_path)

if __name__ == "__main__":
    main()
