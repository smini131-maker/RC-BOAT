"""Installation regression: preserve host ML packages and reject false-success imports."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vision_environment', ROOT / 'deployment/jetson/vision_environment.py')
env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(env)


class EnvironmentMigrationTests(unittest.TestCase):
    def builder(self, target):
        target = Path(target)
        target.mkdir(parents=True, exist_ok=True)
        (target / 'pyvenv.cfg').write_text('include-system-site-packages = false\n')

    def test_inherited_environment_backed_up_without_uninstalling_packages(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'vision-venv'
            target.mkdir()
            (target / 'pyvenv.cfg').write_text('include-system-site-packages = true\n')
            (target / 'old_numpy_marker').write_text('preserve me')
            with patch.object(env.venv, 'EnvBuilder') as builder:
                builder.return_value.create.side_effect = self.builder
                env.prepare(target)
                builder.assert_called_once_with(system_site_packages=False, with_pip=True)
            backups = list(target.parent.glob('vision-venv.backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / 'old_numpy_marker').read_text(), 'preserve me')
            self.assertNotIn('true', (target / 'pyvenv.cfg').read_text())
            self.assertFalse((target / 'old_numpy_marker').exists())

    def test_retry_reuses_isolated_environment_and_preserves_local_files(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'vision-venv'
            self.builder(target)
            (target / 'installed_marker').write_text('keep')
            with patch.object(env.venv, 'EnvBuilder') as builder:
                builder.return_value.create.side_effect = self.builder
                env.prepare(target)
            self.assertTrue((target / 'installed_marker').is_file())
            self.assertEqual(list(target.parent.glob('*.backup-*')), [])

    def test_unrecognized_directory_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(RuntimeError, 'unrecognized'):
            env.prepare(Path(folder))

    def test_real_venv_excludes_a_user_site_package(self):
        # Actual subprocess import isolation, no downloads or device access.
        real_builder = env.venv.EnvBuilder
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'vision-venv'
            child_env = dict(os.environ, PYTHONUSERBASE=str(root / 'user'), PYTHONNOUSERSITE='')
            child_env.pop('PYTHONPATH', None)
            base_python = getattr(sys, '_base_executable', sys.executable)
            user_site = Path(subprocess.check_output([base_python, '-c',
                'import site;print(site.getusersitepackages())'], env=child_env, text=True).strip())
            user_site.mkdir(parents=True)
            (user_site / 'rcboat_unrelated_tensorflow.py').write_text('marker=True\n')
            probe = 'import importlib.util,json,site;print(json.dumps([site.ENABLE_USER_SITE,importlib.util.find_spec("rcboat_unrelated_tensorflow") is not None]))'
            self.assertEqual(json.loads(subprocess.check_output([base_python, '-c', probe], env=child_env, text=True)), [True, True])
            with patch.object(env.venv, 'EnvBuilder', return_value=real_builder(with_pip=False)):
                env.prepare(target)
            py = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python3')
            self.assertEqual(json.loads(subprocess.check_output([str(py), '-c', probe], env=child_env, text=True)), [False, False])


class BindingTests(unittest.TestCase):
    def test_only_camera_gpu_bindings_are_shared_not_numpy_or_tensorflow(self):
        found = {name: {'origin': name + '.so', 'package': []}
                 for name in ('cv2', 'numpy', 'tensorflow', 'onnxruntime', 'tensorrt', 'pycuda', 'pytools')}
        self.assertEqual(set(env.binding_plan(found)), {'cv2', 'tensorrt', 'pycuda', 'pytools'})
        self.assertNotIn('pytools', env.binding_plan({'cv2': found['cv2'], 'pytools': found['pytools']}))

    def test_binding_bridge_missing_cv2_fails_and_existing_package_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            site_dir = root / 'lib/site-packages'
            site_dir.mkdir(parents=True)
            with patch.object(env.subprocess, 'check_output', return_value=str(site_dir)):
                with self.assertRaisesRegex(RuntimeError, 'System OpenCV not found'):
                    env.link_bindings(root, {})
                host = root / 'host/cv2'
                host.mkdir(parents=True)
                (site_dir / 'cv2').mkdir()
                with self.assertRaisesRegex(RuntimeError, 'refusing to overwrite'):
                    env.link_bindings(root, {'cv2': {'origin': str(host / '__init__.py'), 'package': [str(host)]}})

    def test_camera_package_bridge_is_repeatable_without_sharing_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'venv'
            site_dir = target / 'lib/site-packages'
            site_dir.mkdir(parents=True)
            host = root / 'host/cv2'
            host.mkdir(parents=True)
            found = {'cv2': {'origin': str(host / '__init__.py'), 'package': [str(host)]}}
            calls = []
            # Windows test accounts may lack symlink privileges. Exercise planning,
            # paths and metadata; real Jetson symlinks need an on-device check.
            def record(dest, source, target_is_directory=False):
                calls.append((dest, source, target_is_directory))
            with patch.object(env.subprocess, 'check_output', return_value=str(site_dir)), \
                 patch.object(Path, 'symlink_to', record):
                env.link_bindings(target, found)
            self.assertEqual(calls, [(site_dir / 'cv2', host, True)])
            self.assertEqual(json.loads((target / 'rcboat_bindings.json').read_text()), {'cv2': str(host)})


    def test_gpu_only_bridge_preserves_camera_and_excludes_other_user_packages(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'venv';site_dir=target/'lib/site-packages';site_dir.mkdir(parents=True)
            source=root/'host/tensorrt';source.mkdir(parents=True)
            record=target/'rcboat_bindings.json';record.write_text(json.dumps({'cv2':'existing-camera-binding'}))
            found={name:dict(origin=str(source/'__init__.py'),package=[str(source)]) for name in ('tensorrt','tensorflow','numpy')}
            linked=[]
            with patch.object(env.subprocess,'check_output',return_value=str(site_dir)),patch.object(Path,'symlink_to',lambda dest,src,**kwargs:linked.append((dest,src))):
                env.link_bindings(target,found,gpu_only=True)
            self.assertEqual(linked,[(site_dir/'tensorrt',source)])
            self.assertEqual(json.loads(record.read_text()),dict(cv2='existing-camera-binding',tensorrt=str(source)))


class PreflightTests(unittest.TestCase):
    @contextlib.contextmanager
    def preflight(self, inherited=False, array_ok=True, providers=True, tensorflow=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'pyvenv.cfg').write_text('include-system-site-packages = %s\n' % str(inherited).lower())
            np = types.ModuleType('numpy')
            np.__version__ = '1.23.5'; np.__file__ = str(root / 'numpy/__init__.py')
            np.zeros = lambda *a, **kw: object(); np.uint8 = object()
            cv = types.ModuleType('cv2')
            cv.__version__ = '4.8.0'; cv.__file__ = '/host/cv2/__init__.py'; cv.COLOR_BGR2GRAY = 1
            cv.cvtColor = lambda *a: types.SimpleNamespace(shape=(8, 8) if array_ok else (0, 0))
            cv.getBuildInformation = lambda: 'GStreamer: YES'
            ort = types.ModuleType('onnxruntime')
            ort.__version__ = '1.16.3'; ort.__file__ = str(root / 'onnxruntime/__init__.py')
            ort.get_available_providers = lambda: ['CPUExecutionProvider'] if providers else []
            with patch.object(env.sys, 'prefix', str(root)), patch.object(env.sys, 'base_prefix', '/base'), \
                 patch.object(env.sys, 'path', []), patch.object(env.site, 'ENABLE_USER_SITE', False), \
                 patch.dict(sys.modules, numpy=np, cv2=cv, onnxruntime=ort), \
                 patch.object(env.importlib.util, 'find_spec', return_value=object() if tensorflow else None):
                yield np

    def test_inherited_environment_is_rejected(self):
        with self.preflight(inherited=True), self.assertRaisesRegex(RuntimeError, 'still inherited'):
            env.check()

    def test_abi_operation_failure_cannot_print_success(self):
        out = io.StringIO()
        with self.preflight(array_ok=False), contextlib.redirect_stdout(out), \
             self.assertRaisesRegex(RuntimeError, 'interoperability'):
            env.check()
        self.assertNotIn('VISION_ENVIRONMENT_OK', out.getvalue())

    def test_missing_ort_provider_and_tensorflow_leak_are_rejected(self):
        with self.preflight(providers=False), self.assertRaisesRegex(RuntimeError, 'CPU provider'):
            env.check()
        with self.preflight(tensorflow=True), self.assertRaisesRegex(RuntimeError, 'TensorFlow is visible'):
            env.check()

    def test_numpy_loaded_from_host_is_rejected(self):
        with self.preflight() as np, self.assertRaisesRegex(RuntimeError, 'Unexpected vision package'):
            np.__file__ = '/host/numpy/__init__.py'
            env.check()

    def test_success_requires_array_operation_and_expected_package_versions(self):
        out = io.StringIO()
        with self.preflight(), contextlib.redirect_stdout(out):
            env.check()
        self.assertIn('VISION_ENVIRONMENT_OK', out.getvalue())
        self.assertIn('"tensorflow_visible": false', out.getvalue())


if __name__ == '__main__':
    unittest.main()
