def test_shipping_overhead_families():
    from experiments._harness import shipping_overhead, replication_overhead
    from radp.common.types import Stage, DeviceId, LayerIdx
    # head [1..15] excluded; non-head layer counts 2,2,4,1 → 4 non-head stages
    placement = [
        Stage(LayerIdx(1),  LayerIdx(15), DeviceId("h")),
        Stage(LayerIdx(16), LayerIdx(17), DeviceId("a")),
        Stage(LayerIdx(18), LayerIdx(19), DeviceId("b")),
        Stage(LayerIdx(20), LayerIdx(23), DeviceId("c")),
        Stage(LayerIdx(24), LayerIdx(24), DeviceId("d")),
    ]
    # unit sizes: hidden_dim = n_heads*head_dim = 1; mirror/stage = 1; 4 stages → mirror=4
    # kv/stage = layers*2; Σ = (2+2+4+1)*2 = 18
    s = shipping_overhead(placement, n_heads=1, head_dim=1, itemsize=1)
    assert s["input_mirror_bytes_per_step"] == 4
    assert s["kv_column_bytes_per_step"] == 18
    sbs = s["shipping_bytes_per_step"]
    # parity == replicate (mirror + same KV columns)
    assert sbs["parity"] == sbs["replicate"] == 22
    # mirror-only families equal and NOT zero
    assert sbs["surgical"] == sbs["full_replay"] == sbs["reactive"] == 4
    # KV column is the parity−surgical delta
    assert sbs["parity"] - sbs["surgical"] == s["kv_column_bytes_per_step"]
    # KV column term matches replication_overhead's Σ (replicate_bytes)
    o = replication_overhead(placement, n_heads=1, head_dim=1, itemsize=1)
    assert s["kv_column_bytes_per_step"] == o["replicate_bytes"]


def test_replication_overhead_reports_raid6():
    from experiments._harness import replication_overhead
    from radp.common.types import Stage, LayerIdx, DeviceId
    placement = [
        Stage(LayerIdx(1), LayerIdx(4), DeviceId("head")),   # head, not stored
        Stage(LayerIdx(5), LayerIdx(8), DeviceId("b")),      # 4 layers
        Stage(LayerIdx(9), LayerIdx(10), DeviceId("c")),     # 2 layers
    ]
    r = replication_overhead(placement, n_heads=16, head_dim=64, itemsize=2)
    # parity = max stage = 4 layers; raid6 = two blobs of that width
    assert r["raid6_bytes"] == 2 * r["parity_bytes"]
    # raid6 still < replicate when non-head stages >= 3; here 2 stages -> raid6 >= replicate
    assert r["replicate_bytes"] == r["per_stage"][0][1] + r["per_stage"][1][1]
