import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from archive_raw_sessions import archive, ROOT


class RawArchiveTests(unittest.TestCase):
    def test_round_trip_dedup_and_index_survives_missing_working_copies(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'research/build') as temporary:
            root=Path(temporary); folders=[root/'a',root/'b']; output=root/'archive'
            raw={'manifest.json':json.dumps(dict(id='MagAir-synthetic',schemaVersion=1,status='completed')).encode(),
                 'magnetometer.csv':'timestamp_s,bx_uT\n1,한글\n'.encode()}
            for folder in folders:
                folder.mkdir()
                for name,data in raw.items(): (folder/name).write_bytes(data)
                (folder/'.env').write_text('not an experiment file')
            with contextlib.redirect_stdout(io.StringIO()): archive(folders,output)
            index=json.loads((output/'index.json').read_text())['sessions']
            self.assertEqual(len(index),1);self.assertEqual(len(index[0]['sources']),2)
            with zipfile.ZipFile(output/index[0]['archive']) as z:
                self.assertEqual(set(z.namelist()),{'MagAir-synthetic/'+n for n in raw})
                for name,data in raw.items():self.assertEqual(z.read('MagAir-synthetic/'+name),data)
            (folders[0]/'magnetometer.csv').write_bytes(b'new snapshot\n')
            with contextlib.redirect_stdout(io.StringIO()): archive([folders[0]],output)
            self.assertEqual(len(json.loads((output/'index.json').read_text())['sessions']),2)
            with contextlib.redirect_stdout(io.StringIO()): archive([],output)
            self.assertEqual(len(json.loads((output/'index.json').read_text())['sessions']),2)


if __name__=='__main__':unittest.main()
