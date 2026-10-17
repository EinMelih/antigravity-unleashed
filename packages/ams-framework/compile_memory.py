import os
import re
from pathlib import Path

# Character limits from system guidelines (excluding code blocks / comments)
USER_LIMIT = 1500
MEMORY_LIMIT = 2500

def get_clean_user_length(content: str) -> int:
    """Return character count of USER.md, excluding markdown code blocks."""
    # Remove code blocks fenced with ```
    clean_content = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
    return len(clean_content)

def get_clean_memory_length(content: str) -> int:
    """Return character count of MEMORY.md, excluding html comment blocks."""
    # Remove comment blocks fenced with <!-- and -->
    clean_content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    return len(clean_content)

def compile_file(base_name: str, config_dir: Path) -> None:
    pc_file = config_dir / f"{base_name}.pc.md"
    server_file = config_dir / f"{base_name}.server.md"
    out_file = config_dir / f"{base_name}.md"

    # 1. Initialize pc_file if not existing but out_file is available
    if not pc_file.exists() and out_file.exists():
        print(f"Initializing {pc_file.name} from {out_file.name} (stripping banners)...")
        try:
            with open(out_file, "r", encoding="utf-8") as sf:
                lines = sf.readlines()
            # Strip auto-generated comments if they exist as header
            if lines and "AUTO-GENERATED FILE" in lines[0]:
                lines = lines[1:]
            with open(pc_file, "w", encoding="utf-8") as df:
                df.writelines(lines)
        except OSError as e:
            print(f"Error initializing {pc_file.name}: {e}")

    # Create empty dummy PC file if still missing
    if not pc_file.exists():
        try:
            with open(pc_file, "w", encoding="utf-8") as f:
                f.write(f"# {base_name.capitalize()} (PC)\n\n")
        except OSError as e:
            print(f"Error creating dummy file {pc_file.name}: {e}")
            return

    content_parts = []
    content_parts.append(
        f"<!-- AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY. EDIT {base_name}.pc.md OR {base_name}.server.md INSTEAD -->"
    )

    # Read PC-specific content
    pc_content = ""
    try:
        if pc_file.exists():
            with open(pc_file, "r", encoding="utf-8") as f:
                pc_content = f.read().strip()
                if pc_content:
                    content_parts.append(pc_content)
    except OSError as e:
        print(f"Error reading {pc_file.name}: {e}")

    # Read Server-specific content
    server_content = ""
    try:
        if server_file.exists():
            with open(server_file, "r", encoding="utf-8") as f:
                server_content = f.read().strip()
                if server_content:
                    content_parts.append("\n---\n")
                    content_parts.append(server_content)
    except OSError as e:
        print(f"Error reading {server_file.name}: {e}")

    new_content = "\n".join(content_parts) + "\n"

    # 2. Memory Budget Check (excluding comments/code blocks as per system rules)
    if base_name == "USER":
        clean_len = get_clean_user_length(new_content)
        if clean_len > USER_LIMIT:
            print(f"⚠️  WARNING: USER.md exceeds character budget ({clean_len}/{USER_LIMIT} limit). Needs self-compaction!")
    elif base_name == "MEMORY":
        clean_len = get_clean_memory_length(new_content)
        if clean_len > MEMORY_LIMIT:
            print(f"⚠️  WARNING: MEMORY.md exceeds character budget ({clean_len}/{MEMORY_LIMIT} limit). Needs self-compaction!")

    # 3. Read current file content to prevent redundant disk writes (maintains git mtime sanity)
    current_content = ""
    if out_file.exists():
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                current_content = f.read()
        except OSError:
            pass

    if current_content != new_content:
        # Atomic write to avoid data corruption
        temp_file = out_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(temp_file, out_file)
            print(f"Compiled {out_file.name} successfully.")
        except OSError as e:
            print(f"Error writing to {out_file.name}: {e}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
    else:
        print(f"{out_file.name} is up to date (no changes detected).")

def main() -> None:
    # Allow config dir override via environment variable, falling back to home dir
    env_dir = os.environ.get("GEMINI_CONFIG_DIR")
    if env_dir:
        config_dir = Path(env_dir).resolve()
    else:
        config_dir = Path(os.path.expanduser("~/.gemini/config")).resolve()

    if not config_dir.exists():
        print(f"Error: Config directory not found at {config_dir}")
        return

    compile_file("MEMORY", config_dir)
    compile_file("USER", config_dir)

if __name__ == "__main__":
    main()
