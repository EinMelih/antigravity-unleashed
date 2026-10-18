#!/usr/bin/env python3
"""
Antigravity Full Reverse Engineering Extraction Pipeline
Orchestrates end-to-end extraction from an Antigravity installation or baseline archive:
1. Re-validates and refreshes extracted Electron & React bundle sources.
2. Extracts UI internals (IPC channels, shortcuts/actions, feature flags, user tiers) -> catalog/ui_internals.json.
3. Decodes Protobuf descriptors and reconstructs .proto files + Connect service schemas -> proto/** & catalog/rpc_schema.json.
4. Performs native binary analysis of language_server.exe, webm_encoder.exe, elevate.exe -> catalog/binary_analysis.json.
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Add current scripts directory to path to allow relative imports
SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from extract_ui_internals import extract_ui_internals
from extract_proto_schemas import extract_proto_schemas
from extract_binary_analysis import extract_binary_analysis


def discover_antigravity_dir(user_specified=None):
    if user_specified and os.path.exists(user_specified):
        return Path(user_specified)

    candidates = [
        Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Antigravity")),
        Path(os.path.expanduser(r"~\AppData\Local\Programs\Antigravity")),
        PACKAGE_ROOT.parent.parent / ".gemini" / "antigravity" / "scratch" / "upstream_baselines" / "2.24.0",
        Path(os.path.expanduser(r"~/.gemini/antigravity/scratch/upstream_baselines/2.24.0")),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def run_pipeline(antigravity_dir=None, output_dir=None, bundle_path=None):
    start_time = time.time()
    print("=" * 70)
    print("ANTIGRAVITY FULL EXTRACTION PIPELINE (v2.24.0)")
    print("=" * 70)

    if output_dir is None:
        target_dir = PACKAGE_ROOT
    else:
        target_dir = Path(output_dir)

    target_dir.mkdir(parents=True, exist_ok=True)
    catalog_dir = target_dir / "catalog"
    proto_dir = target_dir / "proto"
    extracted_dir = target_dir / "extracted"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    proto_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    agy_dir = discover_antigravity_dir(antigravity_dir)
    print(f"[*] Package Target Directory: {target_dir}")
    print(f"[*] Host Antigravity Directory: {agy_dir}")

    # --- Step 1: Verify / Synchronize Extracted Sources ---
    print("\n--- [Step 1/4] Verifying Extracted Source Trees ---")
    electron_dist = extracted_dir / "electron" / "dist"
    frontend_dir = extracted_dir / "frontend"

    if electron_dist.exists():
        js_files = list(electron_dist.rglob("*.js"))
        print(f"  [OK] Extracted Electron tree present ({len(js_files)} JS files in dist/)")
    else:
        print(f"  [!] Notice: Electron dist/ not yet at {electron_dist}")

    if frontend_dir.exists():
        formatted_bundle = frontend_dir / "main_root.formatted.js"
        modules_dir = frontend_dir / "modules"
        has_bundle = formatted_bundle.exists() and formatted_bundle.stat().st_size > 1000000
        has_modules = modules_dir.exists() and len(list(modules_dir.glob("*.js"))) >= 5
        print(f"  [OK] Frontend React tree present (formatted bundle: {has_bundle}, modules: {has_modules})")

    # --- Step 2: Extract UI Internals Catalog ---
    print("\n--- [Step 2/4] Extracting UI Internals Catalog ---")
    ui_catalog_path = catalog_dir / "ui_internals.json"
    ui_catalog = extract_ui_internals(output_path=ui_catalog_path)
    summary = ui_catalog.get("summary", {})
    print(f"  [OK] UI Internals catalog generated: {summary.get('ipc_channels_count')} IPC channels, "
          f"{summary.get('actions_count')} actions, {summary.get('feature_flags_count')} feature flags, "
          f"{summary.get('user_tiers_count')} user tiers")

    # --- Step 3: Extract Protobuf & Connect RPC Schemas ---
    print("\n--- [Step 3/4] Extracting Protobuf & Connect Schemas ---")
    rpc_catalog_path = catalog_dir / "rpc_schema.json"
    if bundle_path is None:
        bundle_candidates = [
            frontend_dir / "main_bundle.js",
            PACKAGE_ROOT.parent.parent / ".temp_reverse" / "main_bundle.js",
        ]
        for bc in bundle_candidates:
            if bc.exists():
                bundle_path = str(bc)
                break

    extract_proto_schemas(
        bundle_path=bundle_path,
        proto_dir=str(proto_dir),
        catalog_path=str(rpc_catalog_path)
    )
    print(f"  [OK] Reconstructed .proto schemas written to: {proto_dir}")
    print(f"  [OK] Connect RPC catalog saved to: {rpc_catalog_path}")

    # --- Step 4: Extract Native Binary Analysis ---
    print("\n--- [Step 4/4] Performing Language Server Binary Analysis ---")
    bin_catalog_path = catalog_dir / "binary_analysis.json"
    if agy_dir and agy_dir.exists():
        bin_data = extract_binary_analysis(
            antigravity_dir=str(agy_dir),
            output_path=str(bin_catalog_path)
        )
        print(f"  [OK] Binary analysis catalog saved to: {bin_catalog_path}")
    else:
        print("  [!] Skipping binary re-analysis: Antigravity installation not found.")

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"EXTRACTION PIPELINE COMPLETED SUCCESSFULLY in {elapsed:.2f}s (EXIT 0)")
    print("=" * 70)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Automated reproducible extraction pipeline for Google Antigravity reverse engineering."
    )
    parser.add_argument(
        "--antigravity-dir", "-a",
        default=None,
        help="Path to Antigravity installation (default: auto-detected from %LOCALAPPDATA%\\Programs\\Antigravity)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Target output directory for reverse engineering package (default: packages/antigravity-reverse)"
    )
    parser.add_argument(
        "--bundle-path", "-b",
        default=None,
        help="Path to main_bundle.js React bundle containing Protobuf descriptors"
    )
    args = parser.parse_args()
    ret = run_pipeline(
        antigravity_dir=args.antigravity_dir,
        output_dir=args.output_dir,
        bundle_path=args.bundle_path
    )
    sys.exit(ret)


if __name__ == "__main__":
    main()
