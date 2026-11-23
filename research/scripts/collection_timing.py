"""Resolve exact, audited timing metadata bugs without editing raw sessions."""
import hashlib
import json
from pathlib import Path

LEGACY = 'printed_3s_prepare_3s_hold_v1'
FAST = 'printed_2s_prepare_2s_hold_v2'
PREPARE3 = 'printed_3s_prepare_2s_hold_v3'
ANNOTATIONS = Path(__file__).resolve().parents[1]/'MagAir/Resources/collection_timing_annotations.json'


def resolve_timing(manifest, manifest_bytes, annotations=None):
    meta = manifest['printedGrid']
    declared = meta.get('timingRevision')
    if declared not in (None, FAST, PREPARE3):
        raise ValueError('Unknown acquisition timing')
    document = json.loads(ANNOTATIONS.read_text()) if annotations is None else annotations
    if document.get('version') != 1:
        raise ValueError('Unsupported timing annotation version')
    for entry in document['annotations']:
        if entry['sessionID'] != manifest['id'] or entry['campaignID'] != meta['campaignID']:
            continue
        if (entry['declaredTimingRevision'] != declared or
                hashlib.sha256(manifest_bytes).hexdigest() != entry['manifestSHA256']):
            raise ValueError('Timing annotation manifest hash/revision mismatch')
        if entry['effectiveTimingRevision'] != LEGACY:
            raise ValueError('Unsupported timing recovery')
        return LEGACY, entry['id']
    return declared or LEGACY, None
