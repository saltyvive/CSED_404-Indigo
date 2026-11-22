"""Fixture labels and explicit, source-scoped legacy annotations; never edit raw data."""
import hashlib
import json
import math
from pathlib import Path

ANNOTATIONS = Path(__file__).resolve().parents[1]/'MagAir/Resources/fixture_pose_annotations.json'
ALPHA_CONVENTION = 'fixture_phi_theta_alpha_v1: theta is elevation at alpha=0; alpha rotates the initial vertical pencil plane about its desk-projection hinge. Positive tips toward fixture-local right, which rotates with phi. Range [-90,90]. At theta=90 use the fixture reference line, never derive it from the zero-length projection. Phi remains whole-holder desk-vertical yaw, not Pencil axial roll.'


def resolve_pose(manifest, manifest_bytes, annotations=None):
    meta = manifest['printedGrid']; pose = dict(meta['pose']); annotation_id = None
    if pose.get('alphaDegrees') is None:
        document = json.loads(ANNOTATIONS.read_text()) if annotations is None else annotations
        if document.get('version') != 1:
            raise ValueError('Unsupported fixture annotation version')
        for entry in document['annotations']:
            if (entry['campaignID'] == meta['campaignID'] and
                    manifest['id'] in entry['sessionManifestSHA256'] and
                    all(pose[k] == entry[v] for k, v in [('phiDegrees', 'expectedPhiDegrees'),
                        ('thetaDegrees', 'expectedThetaDegrees'), ('tipHeightMM', 'expectedTipHeightMM'),
                        ('tipContact', 'expectedTipContact')])):
                if hashlib.sha256(manifest_bytes).hexdigest() != entry['sessionManifestSHA256'][manifest['id']]:
                    raise ValueError('Legacy annotation manifest hash mismatch')
                pose.update(alphaDegrees=entry['alphaDegrees'], alphaLabelSource=entry['alphaLabelSource'],
                            alphaDefinition=ALPHA_CONVENTION)
                annotation_id = entry['id']
                break
    alpha = pose.get('alphaDegrees')
    if alpha is None:
        raise ValueError('Unknown legacy alpha: explicit user-confirmed annotation required')
    if not math.isfinite(alpha) or not -90 <= alpha <= 90:
        raise ValueError('Invalid alpha label')
    if pose.get('alphaDefinition') != ALPHA_CONVENTION or not pose.get('alphaLabelSource'):
        raise ValueError('Missing alpha convention/source')
    if (pose['thetaDegrees'] < 90 or alpha != 0) and not pose.get('tiltDirectionAtPhiZero', '').strip():
        raise ValueError('Fixture hinge reference missing')
    return pose, annotation_id
