import os
import subprocess
import sys

def escape_for_template_literal(text):
    # Order of replacements is critical!
    # 1. Escape backslashes first, so that they don't escape our next replacement characters
    text = text.replace('\\', '\\\\')
    # 2. Escape backticks
    text = text.replace('`', '\\`')
    # 3. Escape template literal interpolations to prevent Node/Electron from evaluating them at load-time
    text = text.replace('${', '\\${')
    return text

def build():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, '..'))
    src_dir = os.path.join(project_root, 'src')
    ui_dir = os.path.join(src_dir, 'ui')

    # Paths to modular source files
    main_path = os.path.join(ui_dir, 'main.js')
    draft_saver_path = os.path.join(ui_dir, 'draftSaver.js')
    quota_watcher_path = os.path.join(ui_dir, 'quotaWatcher.js')
    task_tracker_path = os.path.join(ui_dir, 'taskTracker.js')
    reviews_dashboard_path = os.path.join(ui_dir, 'reviewsDashboard.js')
    update_release_info_path = os.path.join(ui_dir, 'updateReleaseInfo.js')
    modals_path = os.path.join(ui_dir, 'modals.js')
    antigravity_hub_bridge_path = os.path.join(ui_dir, 'antigravityHubBridge.js')
    api_monitor_path = os.path.join(ui_dir, 'apiMonitor.js')

    header_path = os.path.join(ui_dir, 'preload_header.txt')
    footer_path = os.path.join(ui_dir, 'preload_footer.txt')

    output_preload_path = os.path.join(src_dir, 'preload.js')

    # Read files
    try:
        with open(main_path, 'r', encoding='utf-8') as f:
            main_code = f.read()
        with open(draft_saver_path, 'r', encoding='utf-8') as f:
            draft_saver_code = f.read()
        with open(quota_watcher_path, 'r', encoding='utf-8') as f:
            quota_watcher_code = f.read()
        with open(task_tracker_path, 'r', encoding='utf-8') as f:
            task_tracker_code = f.read()
        with open(reviews_dashboard_path, 'r', encoding='utf-8') as f:
            reviews_dashboard_code = f.read()
        with open(update_release_info_path, 'r', encoding='utf-8') as f:
            update_release_info_code = f.read()
        with open(modals_path, 'r', encoding='utf-8') as f:
            modals_code = f.read()
        with open(antigravity_hub_bridge_path, 'r', encoding='utf-8') as f:
            antigravity_hub_bridge_code = f.read()
        with open(api_monitor_path, 'r', encoding='utf-8') as f:
            api_monitor_code = f.read()

        with open(header_path, 'r', encoding='utf-8') as f:
            header_code = f.read()
        with open(footer_path, 'r', encoding='utf-8') as f:
            footer_code = f.read()
    except Exception as e:
        print(f"Error reading source files: {e}")
        return False

    # Combine modules into the placeholder in main.js
    modules_combined = (
        draft_saver_code + "\n\n" +
        quota_watcher_code + "\n\n" +
        task_tracker_code + "\n\n" +
        reviews_dashboard_code + "\n\n" +
        update_release_info_code + "\n\n" +
        modals_code + "\n\n" +
        antigravity_hub_bridge_code + "\n\n" + api_monitor_code
    )

    placeholder = "// === INSERT MODULES HERE ==="
    if placeholder not in main_code:
        print(f"Error: Placeholder '{placeholder}' not found in main.js")
        return False

    main_world_script = main_code.replace(placeholder, modules_combined)

    # Escape the combined Main World script for inclusion inside a template literal
    escaped_main_world = escape_for_template_literal(main_world_script)

    # Assemble the final preload.js file
    preload_content = (
        header_code +
        "const amsScriptContent = `" + escaped_main_world + "`;\n\n" +
        footer_code
    )

    # Write to a temporary file and validate both JavaScript layers before install.
    temp_preload_path = output_preload_path + '.build.tmp.js'
    try:
        with open(temp_preload_path, 'w', encoding='utf-8') as f:
            f.write(preload_content)

        outer_check = subprocess.run(
            ['node', '--check', temp_preload_path],
            capture_output=True,
            text=True,
        )
        if outer_check.returncode != 0:
            raise RuntimeError('Preload syntax validation failed:\n' + outer_check.stderr)

        runtime_validator = r"""
const fs = require('fs');
const vm = require('vm');
const preload = fs.readFileSync(process.argv[1], 'utf8');
const marker = 'const amsScriptContent = ';
const start = preload.indexOf(marker) + marker.length;
const footer = preload.indexOf('function showInjectionError', start);
if (start < marker.length || footer < 0) throw new Error('AMS template not found');
const literal = preload.slice(start, footer).trim().replace(/;$/, '');
const source = vm.runInNewContext(literal);
new vm.Script(source, { filename: 'ams-main-world.js' });
"""
        runtime_check = subprocess.run(
            ['node', '-e', runtime_validator, temp_preload_path],
            capture_output=True,
            text=True,
        )
        if runtime_check.returncode != 0:
            raise RuntimeError(
                'AMS main-world syntax validation failed:\n' + runtime_check.stderr
            )

        os.replace(temp_preload_path, output_preload_path)
        print(f"Successfully compiled preload.js to: {output_preload_path}")
        return True
    except Exception as e:
        print(f"Error writing compiled preload.js: {e}")
        try:
            if os.path.exists(temp_preload_path):
                os.unlink(temp_preload_path)
        except OSError:
            pass
        return False

if __name__ == '__main__':
    success = build()
    sys.exit(0 if success else 1)
