"""Pure selector logic for the RAID-6 two-victim fleet trial — no fleet needed."""
from experiments.b1_ft_fleet import pick_two_interior_victims


def _pl(*ranges):
    # each range = (device, start, end); mimic fetch_placement's dict shape
    return [{"device": d, "start": s, "end": e} for d, s, e in ranges]


def test_picks_two_interior_non_head_stages():
    pl = _pl(("h", 1, 5), ("b", 6, 10), ("c", 11, 15), ("d", 16, 20), ("e", 21, 24))
    picks = pick_two_interior_victims(pl)
    devs = [p[0] for p in picks]
    assert devs == ["b", "c"]          # first two interior (exclude head h and last e)
    assert all(p[1] > 1 for p in picks) # never the head
    assert "e" not in devs             # never the last stage


def test_raises_when_too_few_stages():
    import pytest
    pl = _pl(("h", 1, 5), ("b", 6, 10), ("last", 11, 24))  # only 1 interior
    with pytest.raises(ValueError):
        pick_two_interior_victims(pl)
