"""Checks GUI presentation and MAX_PATH-safe Windows local build wiring."""
import pathlib
import unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class MissionControlRegression(unittest.TestCase):
    def test_gui_is_readable(self):
        ui=(ROOT/'windows_gui/app.py').read_text(encoding='utf-8')
        for item in ('RC 보트 관제센터','APP_STYLE','StatusCard','ReadoutCard',
                     '실시간 계기판','GPS 지상 실험','RTK / NTRIP',
                     '비상 정지','cat_boat_icon.ico','READOUTS',
                     'HEADING_CTE','LOS','PURE_PURSUIT','ground_start',
                     'ground_stop','set_remote_pwm','NTRIP'):
            self.assertIn(item,ui,item)
    def test_qt_dependencies_minimal(self):
        deps=(ROOT/'windows_gui/requirements.txt').read_text()
        self.assertIn('PySide6-Essentials',deps)
        self.assertNotIn('PySide6>=',deps)
    def test_short_path_and_cache(self):
        script=(ROOT/'tools/windows/runner.ps1').read_text()
        for item in ('RCBoatBuild','ros-beta2','--workpath','--specpath','--distpath',
                     '--add-data','venv','stage','--icon'):
            self.assertIn(item,script,item)
        self.assertNotIn("$Venv = Join-Path $AppDir '.venv'",script)
    def test_icon_and_safety(self):
        self.assertGreater((ROOT/'windows_gui/assets/cat_boat_icon.ico').stat().st_size,1000)
        config=(ROOT/'catkin_ws/src/rcboat_ros/config/boat.yaml').read_text()
        self.assertIn('propulsion_allowed: false',config)
        self.assertIn('experimental_nav_actuation_enabled: false',config)
if __name__=='__main__':unittest.main()
