#!/usr/bin/env python3
"""
Antigravity Headless CLI Tool
Command-line interface for inspecting and controlling local Antigravity Language Server.
Supports status, models, quota, conversations, and pipeline extraction.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add src to sys.path
SRC_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from client import AntigravityClient, LanguageServerError, AuthenticationError, ConnectionError


def format_quota_summary(quota_data: dict) -> str:
    """Formats quota JSON data into a clean, human-readable terminal display."""
    resp = quota_data.get("response", {})
    groups = resp.get("groups", [])
    if not groups:
        return "No quota groups returned."

    lines = []
    lines.append("=" * 60)
    lines.append("ANTIGRAVITY USER QUOTA SUMMARY")
    lines.append("=" * 60)

    for g in groups:
        title = g.get("displayName", "Unnamed Group")
        lines.append(f"\n[Group] {title}")
        desc = g.get("description")
        if desc:
            lines.append(f"  Info: {desc}")

        buckets = g.get("buckets", [])
        for b in buckets:
            b_name = b.get("displayName") or b.get("bucketId", "Bucket")
            window = b.get("window", "")
            fraction = b.get("remainingFraction", 0.0)
            percent = fraction * 100
            bar_len = 25
            filled = int(round(bar_len * fraction))
            bar = "[" + "=" * filled + " " * (bar_len - filled) + "]"
            reset = b.get("resetTime", "N/A")

            lines.append(f"  * {b_name} ({window}):")
            lines.append(f"    {bar} {percent:5.1f}% remaining")
            lines.append(f"    Resets at: {reset}")

    return "\n".join(lines)


def format_models_list(models_data: dict) -> str:
    """Formats models JSON data into an organized terminal table."""
    resp = models_data.get("response", {})
    models = resp.get("models", {})
    if not models:
        return "No models returned."

    lines = []
    lines.append("=" * 75)
    lines.append(f"{'MODEL ID':<32} {'PROVIDER':<15} {'MAX TOKENS':<12} {'INTERNAL'}")
    lines.append("=" * 75)

    if isinstance(models, dict):
        model_items = sorted(models.items())
    elif isinstance(models, list):
        model_items = [(m.get("model", {}).get("name", "unknown"), m) for m in models]
    else:
        return str(models)

    for model_id, info in model_items:
        provider = info.get("modelProvider", "UNKNOWN").replace("MODEL_PROVIDER_", "")
        max_tokens = info.get("maxTokens", "N/A")
        is_internal = "Yes" if info.get("isInternal") else "No"
        lines.append(f"{model_id:<32} {provider:<15} {str(max_tokens):<12} {is_internal}")

    lines.append("-" * 75)
    lines.append(f"Total available models: {len(model_items)}")
    return "\n".join(lines)


def format_conversations_list(conversations: list) -> str:
    """Formats conversation summaries into a table."""
    if not conversations:
        return "No conversations found in local storage."

    lines = []
    lines.append("=" * 80)
    lines.append(f"{'CONVERSATION ID':<38} {'LAST MODIFIED':<22} {'TITLE'}")
    lines.append("=" * 80)

    for c in conversations:
        cid = c.get("conversation_id", "")
        mod_time = c.get("last_modified_time", "")[:19]
        title = (c.get("title") or "Untitled")[:40]
        lines.append(f"{cid:<38} {mod_time:<22} {title}")

    lines.append("-" * 80)
    lines.append(f"Showing {len(conversations)} conversations.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Antigravity Headless CLI — Direct Language Server inspection & control tool."
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        help="Language Server HTTPS port (auto-discovered if omitted)"
    )
    parser.add_argument(
        "--csrf-token", "-t",
        default=None,
        help="Language Server CSRF token (auto-discovered if omitted)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Language Server host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON response"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Command: status
    subparsers.add_parser("status", help="Query Language Server health and user authentication status")

    # Command: models
    subparsers.add_parser("models", help="List available LLM models and token capacities")

    # Command: quota
    subparsers.add_parser("quota", help="Inspect active user 5h and weekly token quotas")

    # Command: conversations
    conv_p = subparsers.add_parser("conversations", help="List recent conversation summaries from local SQLite storage")
    conv_p.add_argument("--limit", "-n", type=int, default=20, help="Maximum number of conversations to display (default: 20)")
    conv_p.add_argument("--db-path", default=None, help="Explicit path to conversation_summaries.db")

    # Command: trajectory
    traj_p = subparsers.add_parser("trajectory", help="Inspect cascade trajectory for a specific session")
    traj_p.add_argument("cascade_id", help="Cascade session UUID")

    # Command: extract
    ext_p = subparsers.add_parser("extract", help="Trigger automated reverse engineering extraction pipeline")
    ext_p.add_argument("--antigravity-dir", "-a", default=None, help="Path to Antigravity installation")
    ext_p.add_argument("--output-dir", "-o", default=None, help="Output directory for reverse engineering package")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Handle 'extract' command separately as it does not need a running server
    if args.command == "extract":
        scripts_dir = PACKAGE_ROOT / "scripts"
        sys.path.insert(0, str(scripts_dir))
        from extract_all import run_pipeline
        ret = run_pipeline(antigravity_dir=args.antigravity_dir, output_dir=args.output_dir)
        sys.exit(ret)

    # Initialize client for live commands
    try:
        client = AntigravityClient(
            port=args.port,
            csrf_token=args.csrf_token,
            host=args.host
        )
    except Exception as e:
        print(f"Error initializing AntigravityClient: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.command == "status":
            health = client.get_status()
            user_stat = client.get_user_status()
            if args.json:
                print(json.dumps({"health": health, "userStatus": user_stat}, indent=2))
            else:
                u = user_stat.get("userStatus", {})
                print("=" * 60)
                print("ANTIGRAVITY SERVER & USER STATUS")
                print("=" * 60)
                print(f"Server Host:Port : https://{client.host}:{client.port}")
                print(f"User Name        : {u.get('name', 'N/A')}")
                print(f"User Email       : {u.get('email', 'N/A')}")
                plan_info = u.get("planStatus", {}).get("planInfo", {})
                print(f"User Tier        : {plan_info.get('teamsTier', 'N/A')}")
                print(f"Plan Name        : {plan_info.get('planName', 'N/A')}")
                print(f"Fast Autocomplete: {plan_info.get('hasAutocompleteFastMode', False)}")
                print(f"Telemetry Status : {'Disabled' if u.get('disableTelemetry') else 'Enabled'}")
                print(f"Server Health    : OK (HTTP 200)")

        elif args.command == "models":
            models_data = client.get_available_models()
            if args.json:
                print(json.dumps(models_data, indent=2))
            else:
                print(format_models_list(models_data))

        elif args.command == "quota":
            quota_data = client.get_user_quota_summary()
            if args.json:
                print(json.dumps(quota_data, indent=2))
            else:
                print(format_quota_summary(quota_data))

        elif args.command == "conversations":
            convs = client.list_conversations(limit=args.limit, db_path=args.db_path)
            if args.json:
                print(json.dumps(convs, indent=2))
            else:
                print(format_conversations_list(convs))

        elif args.command == "trajectory":
            traj = client.get_cascade_trajectory(args.cascade_id)
            if args.json:
                print(json.dumps(traj, indent=2))
            else:
                print(f"Cascade ID: {args.cascade_id}")
                print(f"Total Steps: {traj.get('numTotalSteps', 0)}")
                print(f"Status: {traj.get('status', 'N/A')}")
                print(f"Generator Metadata Count: {traj.get('numTotalGeneratorMetadata', 0)}")
                print(f"Executor Metadata Count: {traj.get('numTotalExecutorMetadata', 0)}")

    except AuthenticationError as e:
        print(f"Authentication Error: {e}", file=sys.stderr)
        sys.exit(2)
    except ConnectionError as e:
        print(f"Connection Error: {e}", file=sys.stderr)
        sys.exit(3)
    except LanguageServerError as e:
        print(f"Language Server Error: {e}", file=sys.stderr)
        sys.exit(4)
    except Exception as e:
        print(f"Unexpected Error: {e}", file=sys.stderr)
        sys.exit(5)


if __name__ == "__main__":
    main()
