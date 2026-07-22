import numpy as np
from radp.coordinator.replica_cache import ReplicaCache
from radp.common.types import RequestId

R = RequestId(1)
SK = (16, 17)  # a stage's (start_layer, end_layer)


def test_store_get_concatenates_in_position_order():
    c = ReplicaCache(num_stages=3)
    c.store(R, SK, 0, b"\x01\x02")
    c.store(R, SK, 1, b"\x03\x04")
    assert c.get_stage_kv(R, SK) == b"\x01\x02\x03\x04"


def test_store_is_deduped():
    c = ReplicaCache(num_stages=3)
    c.store(R, SK, 0, b"\x01\x02")
    c.store(R, SK, 0, b"\xff\xff")  # re-arriving (stage, pos) ignored
    assert c.get_stage_kv(R, SK) == b"\x01\x02"


def test_get_missing_stage_returns_none():
    c = ReplicaCache(num_stages=3)
    assert c.get_stage_kv(R, SK) is None


def test_is_complete_detects_hole():
    c = ReplicaCache(num_stages=3)
    c.store(R, SK, 0, b"\x01\x02")
    c.store(R, SK, 2, b"\x05\x06")  # position 1 missing
    assert c.is_complete(R, SK, up_to_position=2) is False
    assert c.is_complete(R, SK, up_to_position=0) is True


def test_evict_keeps_sole_request():
    c = ReplicaCache(num_stages=1, max_bytes=1)  # tiny cap
    c.store(R, SK, 0, b"\x01\x02\x03\x04")  # over cap, but sole request
    assert c.get_stage_kv(R, SK) == b"\x01\x02\x03\x04"  # not evicted


def test_evict_drops_oldest_when_second_arrives():
    c = ReplicaCache(num_stages=1, max_bytes=4)
    c.store(R, SK, 0, b"\x01\x02\x03\x04")
    c.store(RequestId(2), SK, 0, b"\x05\x06\x07\x08")  # pushes over cap
    assert c.get_stage_kv(R, SK) is None            # oldest evicted
    assert c.get_stage_kv(RequestId(2), SK) is not None
