from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StaticProjectTests(unittest.TestCase):
    def test_all_python_files_parse(self) -> None:
        source_roots = [ROOT / "jetson_backend", ROOT / "windows_app", ROOT / "tests"]
        for path in (path for source_root in source_roots for path in source_root.rglob("*.py")):
            with self.subTest(path=path):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_no_unstable_tty_paths_in_runtime_files(self) -> None:
        runtime_paths = list((ROOT / "jetson_backend" / "rcboat").rglob("*.py"))
        runtime_paths.append(ROOT / "jetson_backend" / "rcboat_daemon.py")
        for path in runtime_paths:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("/dev/ttyACM", text)

    def test_systemd_runs_as_jetson(self) -> None:
        unit = (ROOT / "jetson_backend" / "rcboat.service").read_text(encoding="utf-8")
        self.assertIn("User=jetson", unit)
        self.assertIn("ExecStart=/home/jetson/rcboat/.venv/bin/python", unit)
        self.assertIn("--config /home/jetson/rcboat/boat_config.json", unit)

    def test_installer_does_not_start_service_implicitly(self) -> None:
        installer = (ROOT / "jetson_backend" / "install_jetson.sh").read_text(encoding="utf-8")
        self.assertNotIn("enable --now", installer)
        self.assertNotIn("systemctl start rcboat.service", installer.replace('echo "  sudo systemctl start rcboat.service"', ""))

    def test_installer_preserves_and_backs_up_recorded_routes(self) -> None:
        installer = (ROOT / "jetson_backend" / "install_jetson.sh").read_text(encoding="utf-8")
        self.assertIn('"routes.json"', installer)
        self.assertIn('if [[ ! -f "$TARGET/routes.json" ]]', installer)
        self.assertIn('cp -a "$TARGET/rcboat" "$BACKUP_DIR/rcboat"', installer)

    def test_installer_exposes_jetpack_gpio_to_virtualenv(self) -> None:
        installer = (ROOT / "jetson_backend" / "install_jetson.sh").read_text(encoding="utf-8")
        self.assertIn("venv --system-site-packages", installer)
        self.assertIn("import Jetson.GPIO", installer)
        self.assertIn("from adafruit_pca9685 import PCA9685", installer)

    def test_windows_deployer_uses_a_fresh_remote_directory(self) -> None:
        deployer = (ROOT / "deploy_jetson.ps1").read_text(encoding="utf-8")
        self.assertIn('Get-Date -Format "yyyyMMdd_HHmmss"', deployer)
        self.assertIn('rcboat_deploy_${Stamp}', deployer)
        self.assertNotIn(':/home/${UserName}/rcboat_deploy"', deployer)

    def test_navigation_uses_auto_cruise_setting_and_not_route_throttle(self) -> None:
        config = json.loads((ROOT / "jetson_backend" / "boat_config.json").read_text(encoding="utf-8"))
        routes = json.loads((ROOT / "jetson_backend" / "routes.json").read_text(encoding="utf-8"))
        self.assertEqual(config["auto_cruise_pwm"], 6650)
        for route in routes["routes"]:
            self.assertNotIn("throttle_pwm", route)


if __name__ == "__main__":
    unittest.main()
