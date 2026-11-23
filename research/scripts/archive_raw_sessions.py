#!/usr/bin/env python3
"""Publish immutable raw-session ZIPs; identical copies deduplicate, differing snapshots stay separate."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {'manifest.json', 'README.txt', 'magnetometer.csv', 'accelerometer.csv',
           'gyroscope.csv', 'device_motion.csv', 'pencil_events.csv'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive(roots, output):
    groups = {}
    for root in roots:
        for manifest in sorted(root.rglob('manifest.json')):
            m = json.loads(manifest.read_text())
            sid = m.get('id', '')
            if not sid.startswith('MagAir-') or m.get('schemaVersion') not in (1, 2):
                continue
            files = {p.name: p.read_bytes() for p in sorted(manifest.parent.iterdir()) if p.name in ALLOWED and p.is_file()}
            inventory = [dict(file=n, bytes=len(data), sha256=sha(data)) for n, data in files.items()]
            digest = sha(json.dumps(inventory, sort_keys=True).encode())
            entry = groups.setdefault((sid, digest), dict(sessionID=sid, snapshotSHA256=digest,
                status=m['status'], files=inventory, sources=[], content=files,
                protocol=m.get('printedGrid', {}).get('protocolID', 'historical_demo'),
                campaignID=m.get('printedGrid', {}).get('campaignID')))
            entry['sources'].append(manifest.parent.relative_to(ROOT).as_posix())
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for (sid, digest), entry in sorted(groups.items()):
        target = output/'raw'/sid/(digest[:16]+'.zip')
        target.parent.mkdir(parents=True, exist_ok=True)
        files = entry.pop('content')
        if not target.exists():
            with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for name, data in files.items():
                    info = zipfile.ZipInfo(sid+'/'+name, date_time=(1980,1,1,0,0,0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    z.writestr(info, data)
        with zipfile.ZipFile(target) as z:
            assert set(z.namelist()) == {sid+'/'+n for n in files}, 'Archive members differ'
            assert all(z.read(sid+'/'+n) == data for n, data in files.items()), 'Archive content differs'
        if target.stat().st_size >= 100*1024*1024:
            raise ValueError('Archive exceeds regular GitHub file limit; use a separately approved storage strategy')
        entry.update(archive=target.relative_to(output).as_posix(), archiveSHA256=sha(target.read_bytes()),
                     archiveBytes=target.stat().st_size)
        entries.append(entry)
    index = dict(version=1, rawPublicationAuthorizedOn='2026-11-24',
                 note='Raw bytes unchanged. Status and snapshots retained; not all sessions are eligible training data.', sessions=entries)
    (output/'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(sessions=len({e['sessionID'] for e in entries}), snapshots=len(entries),
        archiveBytes=sum(e['archiveBytes'] for e in entries), files=sum(len(e['files']) for e in entries),
        maxArchiveBytes=max(e['archiveBytes'] for e in entries)), indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--roots', nargs='+', type=Path, default=[ROOT/'demo/data', ROOT/'research/data'])
    p.add_argument('--output', type=Path, default=ROOT/'datasets')
    args = p.parse_args()
    archive(args.roots, args.output)
