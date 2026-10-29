import contextlib
import io
import json
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
