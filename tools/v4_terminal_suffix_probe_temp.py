from collections import Counter

from src.engines.v4_full_universe_exact_state_frontier import ExactIncomingFrontierIndex, _union_states
from tests.test_v4_exact_frontier_production_scale import _pool, _risks

pools = _pool()
index = ExactIncomingFrontierIndex(pools, _risks(pools), frontier_epsilon=0.01, top_keep=12)
fwd_states = [index._single_state[player.element] for player in pools["FWD"]]
rank_layers = index._monotone_rank_layers(fwd_states)
frontier = index._monotone_frontier(fwd_states)
rank_states = tuple(row for layer in rank_layers for row in layer)
union = _union_states(rank_states, tuple(frontier))
print(
    "TERMINAL_SUFFIX_COMPRESSION",
    {
        "raw": len(fwd_states),
        "rank_skyband": len(rank_states),
        "frontier": len(frontier),
        "union": len(union),
        "rank_layer_sizes": [len(layer) for layer in rank_layers],
    },
    flush=True,
)
