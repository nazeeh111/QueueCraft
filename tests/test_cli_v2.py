import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from queuecraft import Event
from queuecraft.cli import main
from queuecraft.study import study


class RecordingCLITests(unittest.TestCase):
    def test_explicit_recording_metadata_roundtrips_current_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            event=Event(0,-1,0,'S',(('B',100,100_000),('A',102,100_000)))
            source=root/'input.csv';source.write_text(event.csv())
            metadata=root/'recording.json';metadata.write_text(json.dumps({'recording_end_ns':5_000_000_000}))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['simulate',str(source),'--size','25','--recording-metadata',str(metadata),'--out',str(root/'run')]),0)
                self.assertEqual(main(['verify',str(root/'run')]),0)
            config=json.loads((root/'run/config.json').read_text())
            self.assertEqual(config['schema_version'],2)
            self.assertEqual(config['recording_end_ns'],5_000_000_000)

    def test_absent_or_malformed_recording_metadata_is_actionable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            event=Event(0,-1,0,'S',(('B',100,100_000),('A',102,100_000)))
            source=root/'input.csv';source.write_text(event.csv())
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                main(['simulate',str(source),'--out',str(root/'missing')])
            metadata=root/'bad.json';metadata.write_text(json.dumps({'recording_end_ns':None}))
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                main(['simulate',str(source),'--recording-metadata',str(metadata),'--out',str(root/'bad')])
            self.assertFalse((root/'bad').exists())

    def test_original_plan_is_rejected_before_creating_an_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);plan=root/'old.json';plan.write_text('{"version":1}')
            with self.assertRaisesRegex(ValueError,'pinned to source'):
                study(root,plan,root/'output')
            self.assertFalse((root/'output').exists())

    def test_legacy_order_is_not_silently_recomputed_with_current_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'result.json').write_text('{}')
            (root/'config.json').write_text('{"schema_version":1}')
            error=io.StringIO()
            with contextlib.redirect_stderr(error),self.assertRaises(SystemExit):
                main(['verify',str(root)])
            self.assertIn('recorded source version',error.getvalue())


class TypedReplayCLITests(unittest.TestCase):
    """Saved accounting values retain their JSON types across exact replay."""

    def export(self, root):
        source=root/'input.csv'
        source.write_text(Event(0,-1,0,'S',(('B',100,100_000),('A',102,100_000))).csv())
        result=subprocess.run([sys.executable,'-B','-m','queuecraft','simulate',str(source),
            '--side','sell','--size','37','--policy','immediate','--recording-end-ns','7000000000',
            '--deadline','4','--latency-ms','55','--fee-ppm','100','--out',str(root/'order')],
            cwd=root,text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        return root/'order'

    def verify(self, root):
        return subprocess.run([sys.executable,'-B','-m','queuecraft','verify','.'],
            cwd=root,text=True,capture_output=True,timeout=20)

    def test_verify_refuses_numeric_boolean_substitution_at_every_depth(self):
        # Regression: exact replay must distinguish JSON true from integer 1.
        with tempfile.TemporaryDirectory() as folder:
            root=self.export(Path(folder))
            original=json.loads((root/'result.json').read_text())
            self.assertEqual(original['fees'],1)
            cases=[(('fees',),True),(('fills',0,'fee'),True),
                   (('orders',0,'acknowledged'),1),(('decisions',0,'valid'),1),
                   (('fees',),2),(('fees',),1.0)]
            for path,value in cases:
                with self.subTest(path=path,value=value):
                    changed=json.loads(json.dumps(original));target=changed
                    for key in path[:-1]:target=target[key]
                    target[path[-1]]=value
                    (root/'result.json').write_text(json.dumps(changed))
                    before={p.name:p.read_bytes() for p in root.iterdir()}
                    result=self.verify(root)
                    self.assertEqual(result.returncode,2,result.stdout)
                    self.assertIn('fresh replay differs from saved trace',result.stderr)
                    self.assertEqual(result.stdout,'')
                    self.assertEqual({p.name:p.read_bytes() for p in root.iterdir()},before)

    def test_verify_accepts_reordered_keys_and_whitespace_without_rewriting(self):
        with tempfile.TemporaryDirectory() as folder:
            root=self.export(Path(folder))
            for name in ('config.json','result.json'):
                path=root/name
                path.write_text(json.dumps(json.loads(path.read_text()),sort_keys=True,indent=4)+'  \n')
            before={p.name:p.read_bytes() for p in root.iterdir()}
            result=self.verify(root)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['replay'],'exact')
            self.assertEqual(result.stderr,'')
            self.assertEqual({p.name:p.read_bytes() for p in root.iterdir()},before)
