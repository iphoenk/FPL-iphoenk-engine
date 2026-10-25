# V12 lineup scope regression coverage (E02)

`tests/test_audit_lineup_scope.py` pins, without changing any rule, weight or utility:

- `enumerate_legal_xi` equals an independent brute force built only from the published FPL rule (1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD, 11 players) and every XI keeps the goalkeeper separate with one goalkeeper left on the bench.
- A squad that is not exactly 15 players, or has an unknown position, is rejected instead of padded.
- Captain/vice pairs are drawn only from the supplied starters (a non-owned player can never be captain or vice), are never the same player, and are ranked identically for the same input.
- Vice takeover value and probability are weighted by the captain's DNP probability; a captain with zero DNP probability gives the vice zero value; covariance remains reported as not modelled.

Not covered here and not claimed: formation legality after a specific autosub sequence, effective-captain scenarios under chips, and feasible bench regret versus raw bench. They have no reproduced defect and need their own fixtures. `search_scope` / `search_complete` labelling was not added.
