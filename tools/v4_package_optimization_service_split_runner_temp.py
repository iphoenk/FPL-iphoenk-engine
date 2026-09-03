from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source_path = ROOT / "tools/v4_package_optimization_service_split_temp.py"
source = source_path.read_text(encoding="utf-8")

old = '''replace_once(p, '        "package_audit_cpu_ms": statuses["packages"]["ms"],', '        "package_precompute_ms": float(package_manifest.get("duration_ms") or 0.0),')'''
new = '''replace_once(\n    p,\n    '        "wc_decision_cpu_ms": statuses["wc"]["ms"],\\n        "package_audit_cpu_ms": statuses["packages"]["ms"],\\n        "lineup_cpu_ms": statuses["lineup"]["ms"],',\n    '        "wc_decision_cpu_ms": statuses["wc"]["ms"],\\n        "package_precompute_ms": float(package_manifest.get("duration_ms") or 0.0),\\n        "lineup_cpu_ms": statuses["lineup"]["ms"],',\n)'''
if source.count(old) != 1:
    raise RuntimeError(f"ambiguous package timing staging fix: {source.count(old)}")
source = source.replace(old, new)

source = source.replace(
    '"required_paths": ["contract", "health.status", "guardrails.direct_xpts_mutation", "guardrails.direct_xmins_mutation"],\n    "equals": {\n        "guardrails.direct_xpts_mutation": False,\n        "guardrails.direct_xmins_mutation": False,\n    },',
    '"required_paths": ["contract", "health.status", "governance.direct_xpts_multiplier_forbidden", "governance.direct_xmins_mutation_forbidden"],\n    "equals": {\n        "governance.direct_xpts_multiplier_forbidden": True,\n        "governance.direct_xmins_mutation_forbidden": True,\n    },',
)

compiled = compile(source, str(source_path), "exec")
exec(compiled, {"__name__": "__main__", "__file__": str(source_path)})
