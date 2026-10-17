import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "install_startup_task.ps1"
STARTER = REPO_ROOT / "start_services.ps1"


class TestWindowsStartupTaskInstaller(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            INSTALLER.is_file(),
            "install_startup_task.ps1 must provide the supported Windows startup path",
        )
        self.script = INSTALLER.read_text(encoding="utf-8")

    def test_uses_the_repository_start_script_for_the_exact_task(self):
        self.assertIn("Antigravity-Dashboard-Services", self.script)
        self.assertRegex(
            self.script,
            re.compile(r"Join-Path\s+\$projectRoot\s+'start_services\.ps1'", re.IGNORECASE),
        )
        self.assertIn("-NoProfile", self.script)
        self.assertIn("-NonInteractive", self.script)
        self.assertIn("-ExecutionPolicy Bypass", self.script)
        self.assertRegex(
            self.script,
            re.compile(r"WorkingDirectory\s*=\s*\$projectRoot", re.IGNORECASE),
        )

    def test_registers_an_enabled_current_user_logon_task_with_safe_settings(self):
        self.assertRegex(
            self.script,
            re.compile(r"New-ScheduledTaskTrigger[\s\S]*-AtLogOn[\s\S]*-User\s+\$userId"),
        )
        self.assertRegex(
            self.script,
            re.compile(r"New-ScheduledTaskPrincipal[\s\S]*-LogonType\s+Interactive"),
        )
        self.assertRegex(
            self.script,
            re.compile(r"New-ScheduledTaskPrincipal[\s\S]*-RunLevel\s+Limited"),
        )
        for required_setting in (
            "-StartWhenAvailable",
            "-AllowStartIfOnBatteries",
            "-DontStopIfGoingOnBatteries",
            "-MultipleInstances IgnoreNew",
        ):
            self.assertIn(required_setting, self.script)

    def test_supports_read_only_check_and_repairs_only_configuration_drift(self):
        self.assertIn("[switch]$CheckOnly", self.script)
        self.assertIn("Test-HubStartupTaskMatches", self.script)
        self.assertRegex(
            self.script,
            re.compile(r"if\s*\(\$CheckOnly\)[\s\S]*exit\s+[01]", re.IGNORECASE),
        )
        self.assertRegex(
            self.script,
            re.compile(r"if\s*\(\$taskMatches\)[\s\S]*exit\s+0", re.IGNORECASE),
        )
        self.assertIn("Register-ScheduledTask", self.script)
        self.assertIn("-Force", self.script)

    def test_compares_windows_accounts_by_sid_after_task_scheduler_normalization(self):
        self.assertIn("Resolve-WindowsAccountSid", self.script)
        self.assertIn("Test-WindowsAccountEqual", self.script)
        self.assertRegex(
            self.script,
            re.compile(
                r"Test-WindowsAccountEqual\s+-Actual\s+\$Task\.Principal\.UserId"
                r"\s+-Expected\s+\$userId",
                re.IGNORECASE,
            ),
        )

    def test_starter_keeps_a_degraded_api_bridge_running_while_injection_waits(self):
        starter = STARTER.read_text(encoding="utf-8")
        health_match = re.search(
            r"function Test-HubHealthEndpoint\s*\{(?P<body>[\s\S]*?)\n\}",
            starter,
            re.IGNORECASE,
        )
        self.assertIsNotNone(health_match)
        health_body = health_match.group("body")
        self.assertNotIn("payload.ready", health_body)
        self.assertIn("Get-ApiBridgeReadiness", starter)
        self.assertIn("native injection is still waiting", starter.lower())
        self.assertIn("service endpoints are responding", starter.lower())

    def test_starter_launches_the_installed_desktop_once_by_default(self):
        starter = STARTER.read_text(encoding="utf-8")
        self.assertIn("[switch]$SkipDesktopStart", starter)
        self.assertIn("ANTIGRAVITY_DESKTOP_EXE", starter)
        self.assertIn("$env:LOCALAPPDATA", starter)
        self.assertNotRegex(starter, re.compile(r"C:\\\\Users\\\\", re.IGNORECASE))
        self.assertIn("System.Threading.Mutex", starter)
        self.assertRegex(
            starter,
            re.compile(r"Get-Process[\s\S]*Antigravity", re.IGNORECASE),
        )
        self.assertIn("Start-Process", starter)

    def test_drift_check_covers_enabled_and_restart_contract(self):
        matcher = self.script.split("function Test-HubStartupTaskMatches", 1)[1]
        matcher = matcher.split("$existingTask =", 1)[0]
        for expected_check in (
            "$Task.Settings.Enabled -ne $true",
            "[int]$Task.Settings.RestartCount -ne 3",
            "[string]$Task.Settings.RestartInterval -ne 'PT1M'",
            "[string]$Task.Settings.ExecutionTimeLimit -ne 'PT10M'",
        ):
            self.assertIn(expected_check, matcher)


if __name__ == "__main__":
    unittest.main()
