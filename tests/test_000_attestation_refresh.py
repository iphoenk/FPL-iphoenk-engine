from __future__ import annotations

import base64

from src.services import architecture_guard_service as guard
from tools.v4_architecture_guard_attest import main


def test_refresh_and_emit_architecture_attestation() -> None:
    main()
    payload = guard.ATTESTATION_PATH.read_bytes()
    print("V4_ATTESTATION_B64=" + base64.b64encode(payload).decode("ascii"))
    assert False, "temporary attestation extraction stop"
