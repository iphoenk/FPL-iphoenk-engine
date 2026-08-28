from __future__ import annotations
import runpy
from pathlib import Path

_original_unlink = Path.unlink

def _safe_unlink(self: Path, *args, **kwargs):
    normalized = str(self).replace('\\', '/')
    if normalized.endswith('.github/workflows/v496-migration.yml'):
        return None
    return _original_unlink(self, *args, **kwargs)

Path.unlink = _safe_unlink
runpy.run_path('tools/v496_apply.py', run_name='__main__')
