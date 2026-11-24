"""Read-only, post-hoc diagnosis of frozen C; never tune or replace live models."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from train_joint_mlp import ROOT, load_records, predict, row_split, save, summarize


def diagnostic_predictions(model, records, corrected=False):
    fields = [r['fields'][0] if corrected else r['primary'] for r in records]
    output = []
    for r, field, p in zip(records, fields, predict(model, fields)):
        output.append(dict(**p, truth=r['state'], passID=r['passID'], row=r['row'], column=r['column'],
            session=r['session'], trial=r['trial'], field=field, targetXY=r['xy'],
            positionErrorMM=math.hypot(50*(p['xy'][0]-r['xy'][0]), 30*(p['xy'][1]-r['xy'][1]))))
    return output


def reasons(rows):
    result = {}
    for state in ('contact', 'air'):
        selected = [r for r in rows if r['truth'] == state]
        rejected = [r for r in selected if not r['accepted']]
        counts = dict(weakSignal=0, outsideSupport=0, outsideXYBounds=0, middleScore=0)
        # Exclusive categories in the stated diagnostic priority, not added overlaps.
        for r in rejected:
            key = ('weakSignal' if not r['shown'] else 'outsideSupport' if not r['inSupport']
                   else 'outsideXYBounds' if not r['inBounds'] else 'middleScore')
            counts[key] += 1
        wrong = [r for r in selected if r['accepted'] and r['predicted'] != state]
        result[state] = dict(count=len(selected), rejectionReasons=counts,
            wrongWithScoreAtLeast90=sum(max(r['contactScore'], 1-r['contactScore']) >= .9 for r in wrong),
            wrongWithScoreAtLeast95=sum(max(r['contactScore'], 1-r['contactScore']) >= .95 for r in wrong))
        assert sum(counts.values()) == len(rejected)
    return result


def run(source, trained, ab_path, out):
    if out.exists():
        raise SystemExit('Refusing to overwrite existing diagnostic output')
    records, inventory = load_records(source)
    model_path = ROOT/'evaluation/frozen/joint_mlp_contact13_air1.json'
    model_raw = model_path.read_bytes()
    assert model_raw == (ROOT/'MagAir/Resources/joint_mlp_contact13_air1.json').read_bytes()
    model = json.loads(model_raw)
    primary = diagnostic_predictions(model, records)
    original = json.loads((trained/'training_replay.json').read_text())
    assert len(primary) == len(original)
    for a, b in zip(primary, original):
        assert (a['session'], a['trial'], a['predicted']) == (b['session'], b['trial'], b['predicted'])
        assert abs(a['contactScore']-b['contactScore']) < 1e-12
    corrected = diagnostic_predictions(model, records, corrected=True)
    held_corrected = []
    for fold in range(5):
        _, test = row_split(records, fold)
        fm = json.loads((trained/f'fold{fold+1}_model.json').read_text())
        assert set(fm['trainingTrialIDs']).isdisjoint(r['session']+'/'+r['trial'] for r in test)
        held_corrected.extend(diagnostic_predictions(fm, test, corrected=True))
    held_primary = json.loads((trained/'row_holdout.json').read_text())
    ab = json.loads(ab_path.read_text())
    lookup = {(r['session'], r['trial']): r for r in primary}
    ab_summary = {}
    for family in ('A', 'B'):
        items = [r for r in ab['predictions'] if r['family'] == family]
        assert len(items) == len(records)
        for r in items:
            ref = lookup[r['session'], r['trial']]
            assert (r['truth'], r['row'], r['column'], r['targetXY']) == (ref['truth'], ref['row'], ref['column'], ref['targetXY'])
        ab_summary[family] = dict(summary=summarize(items), rejectionReasons={
            state: dict(heightAmbiguous=sum(not r['accepted'] and r['heightAmbiguous'] for r in items if r['truth']==state),
                otherPositionRejection=sum(not r['accepted'] and not r['heightAmbiguous'] for r in items if r['truth']==state))
            for state in ('contact', 'air')})
    # Verify A/B were actually queried with identical three-axis input, not just same GT.
    inputs = json.loads((ab_path.parent/'joint-height-inputs.json').read_text())
    assert len(inputs) == len(records)
    for r in inputs:
        assert np.allclose(r['field'], lookup[r['session'], r['trial']]['field'], rtol=0, atol=1e-10)
    row_diagnostics = []
    for b in json.loads((source/'hover_observations.json').read_text()):
        row = b['row']
        a = [r for r in primary if r['truth']=='air' and r['row']==row]
        c = [r for r in corrected if r['truth']=='air' and r['row']==row]
        def one(rows):
            return dict(correct=sum(r['predicted']=='air' for r in rows), wrong=sum(r['predicted']=='contact' for r in rows),
                abstain=sum(not r['accepted'] for r in rows), medianXYErrorMM=float(np.median([r['positionErrorMM'] for r in rows])))
        row_diagnostics.append(dict(row=row, backgroundDriftUT=float(np.linalg.norm(np.array(b['after']['raw'])-b['before']['raw'])),
            primary=one(a), offlineCorrected=one(c)))
    shifts = {}
    for state in ('contact', 'air'):
        selected = [r for r in records if r['state']==state]
        norms = [np.linalg.norm(np.array(r['primary'])-r['fields'][0]) for r in selected]
        pairs = [(a,b) for a,b in zip(primary,corrected) if a['truth']==state]
        shifts[state] = dict(medianInputDifferenceUT=float(np.median(norms)), p95InputDifferenceUT=float(np.percentile(norms,95)),
            forcedStateChanged=sum(a['closestState']!=b['closestState'] for a,b in pairs),
            displayedStateChanged=sum(a['predicted']!=b['predicted'] for a,b in pairs))
    # Symmetric confidence bands are post-hoc diagnostics, never deployment choices.
    bands = []
    for hi in (.65, .75, .85, .9, .95):
        altered = []
        for r in primary:
            accepted = r['shown'] and r['inSupport'] and r['inBounds'] and not (1-hi < r['contactScore'] < hi)
            altered.append(dict(r, accepted=accepted, predicted=r['closestState'] if accepted else 'uncertain'))
        bands.append(dict(high=hi, low=1-hi, summary=summarize(altered)))
    output = dict(role='post_hoc_frozen_model_diagnosis_not_new_validation_or_tuning',
        modelSHA256=hashlib.sha256(model_raw).hexdigest(), observationInventory=inventory,
        inputFiles={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [ab_path, ab_path.parent/'joint-height-inputs.json', trained/'training_replay.json', trained/'row_holdout.json']},
        limitations=['Offline correction uses future end background and is not deployable real-time evidence.',
            'Training replay is optimistic; row holdout remains within existing campaigns, not an independent air repeat.',
            'No new model was trained, no weights or thresholds changed, no pass2 data used.'],
        AB=ab_summary, CPrimary=dict(summary=summarize(primary), reasons=reasons(primary)),
        COfflineCorrected=dict(summary=summarize(corrected), reasons=reasons(corrected)),
        CRowHoldoutPrimary=dict(summary=summarize(held_primary), reasons=reasons(held_primary)),
        CRowHoldoutOfflineCorrected=dict(summary=summarize(held_corrected), reasons=reasons(held_corrected)),
        inputShift=shifts, airRows=row_diagnostics, diagnosticConfidenceBands=bands)
    out.mkdir(parents=True)
    save(out/'summary.json', output)
    save(out/'offline_corrected_replay.json', corrected)
    save(out/'offline_corrected_holdout.json', held_corrected)
    print(json.dumps({k:output[k] for k in ('CPrimary','COfflineCorrected','CRowHoldoutOfflineCorrected','inputShift','airRows')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'reports/hover3-20261125-pass1')
    parser.add_argument('--trained', type=Path, default=ROOT/'reports/joint-mlp-20261125-v1')
    parser.add_argument('--ab', type=Path, default=ROOT/'build/tests/joint-height-replay.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.trained, args.ab, args.out)
