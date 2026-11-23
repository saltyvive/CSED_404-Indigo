#!/usr/bin/env python3
"""Evaluate a whole unseen pass with a frozen model, save scores, then build the next model."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics as st

from build_grid_model import Projector
from build_printed_grid_model import extract, build, require


def sha(data):
    return hashlib.sha256(data).hexdigest()


def percentile(values, p):
    if not values: return None
    v = sorted(values); k = (len(v)-1)*p; i = int(k)
    return v[i]+(v[min(i+1,len(v)-1)]-v[i])*(k-i)


def metrics(predictions):
    errors = [p['errorMM'] for p in predictions]
    accepted = [p['errorMM'] for p in predictions if p['accepted']]
    n = len(predictions)
    return dict(count=n, meanRadialErrorMM=st.mean(errors), medianRadialErrorMM=st.median(errors),
                p95RadialErrorMM=percentile(errors,.95), radialRMSEMM=math.sqrt(st.mean(e*e for e in errors)),
                acceptedDisplayRate=sum(p['accepted'] for p in predictions)/n,
                candidateDisplayRate=sum(p['shown'] for p in predictions)/n,
                medianAcceptedErrorMM=st.median(accepted) if accepted else None,
                successWithin2p5MM=sum(p['accepted'] and p['errorMM'] <= 2.5 for p in predictions)/n,
                successWithin5MM=sum(p['accepted'] and p['errorMM'] <= 5 for p in predictions)/n)


def score(frozen, training, evaluation, test_pass, digest):
    previous = list(range(1,test_pass))
    require(test_pass in (2,3) and frozen['printedGridContext']['passes'] == previous, 'Wrong frozen training passes')
    train_ids = {b['session'] for b in training}; eval_ids = {b['session'] for b in evaluation}
    require(train_ids == set(frozen['sourceSessions']) and not train_ids & eval_ids, 'Training/evaluation overlap or wrong training sources')
    require(len(evaluation)==13 and {(b['repetition'], b['row']) for b in evaluation} ==
            {(test_pass,r) for r in range(1,14)}, 'A complete unseen pass is required')
    rebuilt = json.loads(json.dumps(build(training, previous)))
    require(set(rebuilt['trainingTrialIDs']) == set(frozen['trainingTrialIDs']), 'Frozen training trials mismatch')
    require(all(rebuilt[k] == frozen.get(k) for k in rebuilt if k != 'trainingTrialIDs'), 'Training inputs do not reproduce frozen model')
    reference = training[0]
    for b in evaluation:
        require(all(b[k] == reference[k] for k in ('campaignID','device','setup','pose')), 'Evaluation setup/pose mismatch')
        require(b['evaluationModelSHA256'] == digest and b['evaluationTrainingPasses'] == previous,
                'Collection did not record this frozen evaluation model')
    projector = Projector(frozen)
    primary, causal, offline = [], [], []
    for batch in evaluation:
        for point in batch['points']:
            def predict(field):
                pred = projector.project(field)
                return dict(session=batch['session'], trial=point['trial'], row=point['row'], column=point['column'],
                            targetXY=point['xy'], errorMM=math.hypot(50*(pred['xy'][0]-point['xy'][0]),30*(pred['xy'][1]-point['xy'][1])), **pred)
            # Test predictions never use the future end background or target coordinate as an input.
            primary.append(predict([v-b for v,b in zip(point['raw'],batch['before']['raw'])]))
            for frame in point['causalFrames']: causal.append(predict(frame['filteredDeltaUT']))
            offline.append(predict(point['deltaUT']))
    report = dict(protocol='whole_pass_test_then_train_v1', evaluatedPass=test_pass, trainingPasses=previous,
                  frozenModelSHA256=digest, trainingSessions=sorted(train_ids), evaluationSessions=sorted(eval_ids),
                  primaryMode='steady_trial_median_with_preceding_row_background_only',
                  primary=metrics(primary), causalReplay=metrics(causal), offlineEndBackgroundDiagnostic=metrics(offline),
                  perRow={str(r):metrics([p for p in primary if p['row']==r]) for r in range(1,14)},
                  perRegion={name:metrics([p for p in primary if (p['row'] in (1,13) or p['column'] in (1,21)) == boundary])
                             for name,boundary in [('boundary',True),('interior',False)]},
                  limits=['Unseen placements at previously trained grid coordinates, not unseen-space or handwriting accuracy.',
                          'Primary uses a trimmed whole-hold median; causal replay is a separate three-frame-per-placement diagnostic.',
                          'No-display/ambiguous predictions count as failures in threshold success rates; candidate errors remain reported.',
                          'The evaluated pass may train the next model, but cannot independently test that next model.',
                          'A duration/automatic-collection change can affect between-pass scores; this is not a pure learning-curve comparison.'])
    return report, dict(primary=primary, causal=causal, offline=offline)


def run(model_path, training_paths, evaluation_paths, test_pass, out, **review):
    require(not out.exists(), 'Use a fresh output directory; evaluations are immutable')
    model_bytes = model_path.read_bytes(); frozen = json.loads(model_bytes); digest = sha(model_bytes)
    training = [extract(p, **review) for p in training_paths]
    evaluation = [extract(p, **review) for p in evaluation_paths]
    report, predictions = score(frozen,training,evaluation,test_pass,digest)
    out.mkdir(parents=True)
    (out/'frozen_model.json').write_bytes(model_bytes)
    (out/'evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    (out/'predictions.json').write_text(json.dumps(predictions,ensure_ascii=False,indent=2,allow_nan=False))
    inventory = []
    for role, paths in [('train',training_paths),('evaluate',evaluation_paths)]:
        for path in paths:
            for f in sorted(path.iterdir()):
                if f.is_file(): inventory.append(dict(role=role, session=path.name, file=f.name, sha256=sha(f.read_bytes())))
    (out/'source_inventory.json').write_text(json.dumps(inventory,indent=2))
    # Updating happens only AFTER the pre-update evaluation is recorded.
    updated = build(training+evaluation,list(range(1,test_pass+1)))
    (out/'next_model.json').write_text(json.dumps(updated,ensure_ascii=False,indent=2,allow_nan=False))
    m = report['primary']
    table = f"| 1–{test_pass-1} | {test_pass} | {m['medianRadialErrorMM']:.3f} | {m['p95RadialErrorMM']:.3f} | {100*m['successWithin2p5MM']:.1f}% | {100*m['successWithin5MM']:.1f}% | {100*m['acceptedDisplayRate']:.1f}% | `{digest}` |\n"
    (out/'ledger_row.md').write_text(table)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--training-sessions',nargs='+',type=Path,required=True)
    p.add_argument('--evaluation-sessions',nargs='+',type=Path,required=True)
    p.add_argument('--test-pass',type=int,choices=[2,3],required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--allow-reviewed-transient-motion',action='store_true')
    p.add_argument('--review-note')
    a=p.parse_args()
    run(a.model,a.training_sessions,a.evaluation_sessions,a.test_pass,a.out,
        allow_transient_motion=a.allow_reviewed_transient_motion,review_note=a.review_note)
