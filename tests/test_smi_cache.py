import numpy as np
import pytest

pytest.importorskip("smi_tiled")
import h5py
from sciview.processing.smi_cache import read_profiles, fit_profiles, compose_channels, save_analysis


def test_cache_reads_only_profiles_orders_axes_and_fits(tmp_path):
    from smi_tiled.derived.peakfit import PeakDef
    import threading
    path = tmp_path / "uid.h5"
    q = np.linspace(1, 3, 200)
    iq = np.array([a*np.exp(-0.5*((q-2)/0.08)**2) + 1 for a in (10, 20, 30)])
    with h5py.File(path, "w") as f:
        f.create_dataset("reduction/pf_iq_I", data=iq)
        f.create_dataset("reduction/pf_iq_q", data=q)
        f.create_dataset("primary/seq_num", data=[3, 1, 2])
        f.create_dataset("primary/target_file_name", data=np.array([b"sample_eV2600", b"sample_eV2400", b"sample_eV2500"]))
    before = path.read_bytes()
    profiles = read_profiles(path)
    np.testing.assert_allclose(profiles.axes["fn:eV"], [2400, 2500, 2600])
    peak = PeakDef("p1", 1.7, 2.3, link="linked")
    profiles.fits = fit_profiles(profiles, [peak], threading.Event())
    np.testing.assert_allclose(profiles.fits[peak.key()]["center"], 2, atol=.01)
    out = tmp_path / "output.h5"
    save_analysis(profiles, [peak], out)
    with h5py.File(out) as f:
        assert f.attrs["q_units"] == "nm^-1"
        assert f["peakfit/0/area"].shape == (3,)
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="overwrite"):
        save_analysis(profiles, [peak], path)


def test_composite_respects_zero_gain_and_missing_values():
    values = np.array([0., 1., np.nan])
    assert not compose_channels([(values, (1, 0, 0), 0, False)]).any()
    rgb = compose_channels([(values, (0, 1, 0), 1, False)])
    assert rgb[1, 1] == 1
    assert np.isfinite(rgb).all()
    assert not rgb[:, [0, 2]].any()
