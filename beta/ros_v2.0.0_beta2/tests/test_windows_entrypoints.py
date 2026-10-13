import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]

class WindowsEntrypointRegression(unittest.TestCase):
    def test_ascii_batch_and_silent_where(self):
        for file in ROOT.rglob('*'):
            if file.suffix.lower() not in ('.cmd','.bat'): continue
            source=file.read_bytes().decode('ascii')
            for line in source.splitlines():
                if line.strip().lower().startswith('where '):
                    self.assertIn('>nul',line.lower(),str(file))
        checker=(ROOT/'CHECK_WINDOWS.cmd').read_text(encoding='ascii')
        self.assertIn('-Action CHECK_WINDOWS',checker)
        self.assertIn('RCBOAT_NO_PAUSE',checker)
    def test_python_313_support_and_exe_validation(self):
        src=(ROOT/'tools/windows/runner.ps1').read_text(encoding='utf-8')
        for token in ("'3.11'","'3.12'","'3.13'","Resolve-RCBoatPython","CHECK_WINDOWS","RCBOAT_PYTHON","Start-Transcript","Stop-Transcript","subprocess.run"):
            self.assertIn(token,src)
    def test_upload_targets_correct_beta(self):
        src=(ROOT/'tools/windows/runner.ps1').read_text(encoding='utf-8')
        self.assertIn('beta/ros-v2.0.0-beta.2',src)
        self.assertIn('ros_v2.0.0_beta2',src)
    def test_secondary_scripts_reuse_safe_runner(self):
        for name in ('CHECK_BACKEND','CHECK_ROS','DEPLOY_ROS','INSTALL_ROS','USE_ROS','USE_DAEMON'):
            text=(ROOT/'deployment/windows'/f'{name}.cmd').read_text(encoding='ascii')
            self.assertIn(f'{name}.cmd',text)
            self.assertIn('-Destination',text)
            self.assertIn('exit /b %ERRORLEVEL%',text)
if __name__=='__main__': unittest.main()
