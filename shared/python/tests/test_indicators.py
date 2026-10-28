import numpy as np
import pytest

from showcase_shared.indicators import band, decay, gini, saturate, transport_choice, weighted_quantile_bands
from showcase_shared.ssb_grid import centroid_from_ssbid, parent_ssbid, ssbid_from_xy, xy_from_ssbid


def test_decay_halves_and_cuts_off():
    w = decay([0, 30, 60, 91], half_life=30)
    assert w[0] == pytest.approx(1.0)
    assert w[1] == pytest.approx(0.5)
    assert w[2] == pytest.approx(0.25)
    assert w[3] == 0.0


def test_saturate_reaches_95_percent_at_target():
    assert saturate(0, 10) == pytest.approx(0.0)
    assert saturate(10, 10) == pytest.approx(1 - np.exp(-3))


def test_transport_choice_formula():
    # Like stor rekkevidde gir 100; ingen kollektivrekkevidde gir 0
    assert transport_choice(5, 5, low_total=1) == pytest.approx(100)
    assert transport_choice(0, 5, low_total=1) == pytest.approx(0)
    # 100 · 2·1/(1+3) = 50
    assert transport_choice(1, 3, low_total=1) == pytest.approx(50)
    # Kollektiv bedre enn bil begrenses til 100
    assert transport_choice(4, 2, low_total=1) == pytest.approx(100)
    # Lav samlet rekkevidde skaleres ned: total 0,5 av 1 halverer scoren
    assert transport_choice(0.25, 0.25, low_total=1) == pytest.approx(50)


def test_band_uses_dk_limits_and_inclusive_lower_bound():
    assert list(band([100, 70, 69.9, 55, 45, 30, 22, 15, 14.9, 0])) == [
        "A", "A", "B", "B", "C", "D", "E", "F", "G", "G",
    ]


def test_weighted_quantile_bands_are_descending():
    rng = np.random.default_rng(1)
    s = rng.uniform(0, 100, 1000)
    bands = weighted_quantile_bands(s, np.ones_like(s))
    lowers = [lower for _, lower in bands]
    assert [letter for letter, _ in bands] == ["A", "B", "C", "D", "E", "F", "G"]
    assert lowers == sorted(lowers, reverse=True)
    assert lowers[-1] == 0.0


def test_gini_extremes():
    assert gini([1, 1, 1, 1]) == pytest.approx(0.0, abs=1e-9)
    # Én person har alt: Gini nærmer seg 1 − 1/n
    assert gini([0, 0, 0, 10]) == pytest.approx(0.75)
    # Vekter teller som befolkning
    assert gini([1, 3], weights=[3, 1]) == pytest.approx(gini([1, 1, 1, 3]))


def test_ssbid_round_trip_including_west_norway():
    # Oslo sentrum og Bergen (negativ x i UTM 33)
    for x, y in [(262_400.0, 6_649_300.0), (-31_200.0, 6_731_900.0)]:
        sid = ssbid_from_xy(x, y)
        x0, y0 = xy_from_ssbid(sid)
        assert x0 <= x < x0 + 250 and y0 <= y < y0 + 250
        cx, cy = centroid_from_ssbid(sid)
        assert (cx, cy) == (x0 + 125, y0 + 125)
    # x0 = 262 250, y0 = 6 649 250 → (262 250 + 2 000 000) · 10^7 + 6 649 250
    assert int(ssbid_from_xy(262_400.0, 6_649_300.0)) == 22622506649250
    assert int(parent_ssbid(22622506649250)) == int(ssbid_from_xy(262_400.0, 6_649_300.0, 1000))
