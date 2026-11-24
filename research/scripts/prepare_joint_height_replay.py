"""Prepare stationary training replay queries for the actual Swift joint estimator.

Not a validation split or a reproduction of the live 0.12s filter. Query features
use only the preceding row baseline. Ground-truth fields are evaluator-only.
"""
import argparse
import hashlib
import json
from pathlib import Path


def prepare(source: Path, output: Path):
    rows, inventory = [], []
    for state, name in [('contact', 'contact_observations.json'), ('air', 'hover_observations.json')]:
        raw = (source / name).read_bytes()
        inventory.append(dict(file=name, sha256=hashlib.sha256(raw).hexdigest()))
        for batch in json.loads(raw):
            if state == 'contact' and batch['repetition'] not in (1, 3):
                continue
            assert batch['pose']['tipContact'] == (state == 'contact')
            assert batch['pose']['tipHeightMM'] == (0 if state == 'contact' else 3)
            assert (batch['pose']['phiDegrees'], batch['pose']['thetaDegrees'], batch['pose']['alphaDegrees']) == (0, 90, 0)
            if state == 'air':
                assert batch['repetition'] == 1
            for p in batch['points']:
                rows.append(dict(truth=state, **{'pass': batch['repetition']}, row=p['row'], column=p['column'],
                    field=[v-b for v, b in zip(p['raw'], batch['before']['raw'])], xy=p['xy'],
                    session=p['session'], trial=p['trial']))
    assert len(rows) == 819 and len({(r['session'], r['trial']) for r in rows}) == 819
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, indent=2) + '\n')
    output.with_suffix('.sources.json').write_text(json.dumps(inventory, indent=2) + '\n')
    print(f'Saved {len(rows)} stationary queries; training replay only: {output}')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    prepare(args.source, args.output)
