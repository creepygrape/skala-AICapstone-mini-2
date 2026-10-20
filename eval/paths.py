"""Project-relative inputs and private-only, canonical evaluation artifacts."""

import json
from pathlib import Path
import tempfile

from backend.app.services.video_catalog import ROOT


def project_path(path) -> Path:
    value = Path(path)
    return (value if value.is_absolute() else ROOT / value).resolve()


def private_output(path) -> Path:
    root = ROOT / 'eval/private'
    # A relocated private root would no longer match the root Git ignore rule.
    if root.resolve() != root:
        raise ValueError('eval/private must not be relocated through symlinks')
    target = project_path(path)
    if target == root or not target.is_relative_to(root):
        raise ValueError('Evaluation output must stay inside eval/private/')
    return target


def write_private_json(path, payload):
    """Atomically checkpoint a run without ever creating a public temporary file."""
    target = private_output(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                     prefix='.eval-', suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
