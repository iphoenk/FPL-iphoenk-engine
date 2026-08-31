import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

NODE24_ACTIONS = {
    "actions/checkout": {
        "v7",
        "3d3c42e5aac5ba805825da76410c181273ba90b1",  # v7.0.1
    },
    "actions/setup-python": {
        "v7",
        "5fda3b95a4ea91299a34e894583c3862153e4b97",  # v7.0.0
    },
    "actions/upload-artifact": {
        "v7",
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",  # v7.0.1
    },
    "actions/download-artifact": {
        "v8",
        "v7",
        "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",  # v8.0.1
    },
}


def test_first_party_actions_use_node24_compatible_releases():
    offenders = []
    pattern = re.compile(r"uses:\s*(actions/(?:checkout|setup-python|upload-artifact|download-artifact))@([^\s#]+)")
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        for action, ref in pattern.findall(text):
            if ref not in NODE24_ACTIONS[action]:
                offenders.append(f"{workflow.name}: {action}@{ref}")
    assert offenders == [], "Node20/unknown first-party action refs: " + "; ".join(offenders)
