from pathlib import Path
import tempfile
import unittest

from queuecraft.capture import RawCapture,read_capture


class CaptureTests(unittest.TestCase):
    def test_exact_append_restore_and_shutdown(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"capture.qcraw"
            with RawCapture(path) as capture:
                with self.assertRaises(ValueError):capture.append(b'bad',-1)
                capture.append(b'{"snapshot":1}',10)
                capture.append(b'\x00\xff',11)
                with self.assertRaises(ValueError):capture.append(b'bad',9)
            capture.close()
            self.assertEqual(list(read_capture(path)),[(10,b'{"snapshot":1}'),(11,b'\x00\xff')])
            before=path.read_bytes()
            with self.assertRaises(FileExistsError):RawCapture(path)
            self.assertEqual(path.read_bytes(),before)

    def test_truncation_corruption_and_bounds_require_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"capture.qcraw"
            with RawCapture(path) as capture:
                capture.append(b'payload',1)
                with self.assertRaises(ValueError):capture.append(b'x'*1_048_577,2)
            original=path.read_bytes()
            for index,content in enumerate((original[:-1],original[:12],original[:-1]+b'x')):
                bad=Path(root)/str(index)
                bad.write_bytes(content)
                with self.assertRaises(ValueError):list(read_capture(bad))

    def test_concurrent_file_growth_cannot_evade_total_read_limit(self):
        from unittest.mock import patch
        from queuecraft.capture import MAGIC
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"capture.qcraw"
            with RawCapture(path) as capture:capture.append(b'payload',1)
            original=path.read_bytes()
            with patch('queuecraft.capture.MAX_CAPTURE',len(original)):
                reader=read_capture(path)
                self.assertEqual(next(reader),(1,b'payload'))
                with path.open('ab') as output:output.write(original[len(MAGIC):])
                with self.assertRaises(ValueError):list(reader)
