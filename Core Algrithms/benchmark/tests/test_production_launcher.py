import sys
from pathlib import Path
import tempfile
import subprocess
import json
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from launch_production_cec import prepare_source

class LauncherTests(unittest.TestCase):
    def test_freezes_runnable_source_without_starting_optimizer(self):
        with tempfile.TemporaryDirectory(prefix='cec_source_test_') as tmp:
            out=Path(tmp)/'new_run'
            controller=prepare_source(out)
            self.assertTrue(controller.exists())
            self.assertTrue((out/'source/src/gapo_timetabling/core/hybrid.py').exists())
            self.assertTrue((out/'source/benchmark/.cache/cec2022_official/cec2022_official.dll').exists())
            environment=json.loads((out/'runtime_environment.json').read_text())
            self.assertEqual(len(environment['official_cpp_sha256']),64)
            run=subprocess.run([sys.executable,str(controller),'--help'],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertFalse((out/'runs').exists())
            with self.assertRaises(FileExistsError):prepare_source(out)

if __name__=='__main__':unittest.main()
