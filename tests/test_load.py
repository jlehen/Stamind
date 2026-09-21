"""The load model: the measured TSS, the fallback hierarchy, and RPE divergence.

Pure maths over an activity row — no database, no Garmin client. The ingestion that
feeds it rows is tested in test_garmin.py (ARCHITECTURE §12).
"""
import unittest

from stamind.analytics import load as load_math


class TestTheLoadModel(unittest.TestCase):
    @staticmethod
    def _no_power():
        return {f"power_zone{i}_sec": None for i in range(1, 8)}

    @staticmethod
    def _no_hr():
        return {f"zone{i}_sec": 0 for i in range(1, 6)}

    # --- measured_tss: the stored objective measurement -------------------
    def test_measured_tss_prefers_power(self):
        power = self._no_power()
        power["power_zone2_sec"] = 1800   # 1800 * 0.0117 = 21.06
        power["power_zone3_sec"] = 1800   # 1800 * 0.0178 = 32.04
        hr = {f"zone{i}_sec": 720 for i in range(1, 6)}  # present but power wins
        self.assertEqual(load_math.measured_tss(power, hr), 53.1)

    def test_measured_tss_falls_back_to_hr(self):
        hr = self._no_hr()
        hr["zone2_sec"] = 3600            # 3600 * 0.0111 = 39.96
        self.assertEqual(load_math.measured_tss(self._no_power(), hr), 40.0)

    def test_measured_tss_none_without_zones(self):
        # Pure measurement: no coverage gate, no RPE — None when no zones.
        self.assertIsNone(load_math.measured_tss(self._no_power(), self._no_hr()))

    # --- compute_load: the fallback hierarchy -----------------------------
    def test_load_uses_power(self):
        power = self._no_power()
        power["power_zone4_sec"] = 3600   # 3600 * 0.0250 = 90.0
        load, method, warning = load_math.compute_load(
            power, {f"zone{i}_sec": 720 for i in range(1, 6)}, rpe=6,
            duration_sec=3600)
        self.assertEqual((load, method, warning), (90.0, "power", None))

    def test_load_uses_hr_with_good_coverage(self):
        hr = self._no_hr()
        hr["zone2_sec"] = 3600            # coverage 1.0
        load, method, warning = load_math.compute_load(
            self._no_power(), hr, rpe=4, duration_sec=3600)
        self.assertEqual((load, method, warning), (40.0, "hr", None))

    def test_load_diverts_sparse_hr_to_user_rpe(self):
        hr = self._no_hr()
        hr["zone1_sec"] = 300            # coverage 0.083 < 0.5
        load, method, warning = load_math.compute_load(
            self._no_power(), hr, rpe=3, duration_sec=3600)
        self.assertEqual((load, method, warning), (30.0, "rpe", None))

    def test_load_sparse_hr_no_rpe_warns_and_keeps_hr(self):
        hr = self._no_hr()
        hr["zone1_sec"] = 300            # coverage 0.083, hrTSS = 1.65 -> 1.6/1.7
        load, method, warning = load_math.compute_load(
            self._no_power(), hr, rpe=None, duration_sec=3600)
        self.assertEqual(method, "hr_sparse")
        self.assertIsNotNone(warning)
        self.assertAlmostEqual(load, round(300 * 0.0055, 1))

    def test_load_no_data_no_rpe_warns_zero(self):
        load, method, warning = load_math.compute_load(
            self._no_power(), self._no_hr(), rpe=None, duration_sec=3600)
        self.assertEqual(load, 0.0)
        self.assertEqual(method, "none")
        self.assertIsNotNone(warning)

    def test_load_no_zones_uses_rpe(self):
        load, method, warning = load_math.compute_load(
            self._no_power(), self._no_hr(), rpe=5, duration_sec=3600)
        self.assertEqual((load, method, warning), (50.0, "rpe", None))

    # --- rpe_divergence: hidden-fatigue flag ------------------------------
    @staticmethod
    def _hr_activity(**overrides):
        act = {f"zone{i}_sec": 0 for i in range(1, 6)}
        act.update({f"power_zone{i}_sec": None for i in range(1, 8)})
        act.update({"duration_sec": 3600, "rpe": None, "tss": None})
        act.update(overrides)
        return act

    def test_rpe_divergence_flags_when_rpe_exceeds_measured(self):
        # Measured hrTSS 40 (coverage 1.0); RPE 9 -> sRPE 90 -> ratio 2.25 >= 1.5.
        act = self._hr_activity(zone2_sec=3600, tss=40.0, rpe=9)
        self.assertEqual(load_math.rpe_divergence(act), 2.25)

    def test_rpe_divergence_none_without_rpe(self):
        act = self._hr_activity(zone2_sec=3600, tss=40.0, rpe=None)
        self.assertIsNone(load_math.rpe_divergence(act))

    def test_rpe_divergence_none_when_load_is_rpe_based(self):
        # Sparse HR -> load already came from RPE, so there is no divergence.
        act = self._hr_activity(zone1_sec=300, tss=1.7, rpe=8)  # coverage 0.083
        self.assertIsNone(load_math.rpe_divergence(act))

    def test_activity_load_takes_rpe_when_divergent(self):
        # Trustworthy hrTSS 15 but RPE 4 -> sRPE 40 (ratio 2.67 >= 1.5): the
        # meters under-counted real strain (e.g. strength work), so load = sRPE.
        act = self._hr_activity(zone2_sec=3600, tss=15.0, rpe=4)
        self.assertAlmostEqual(load_math.activity_load(act), 40.0)

    def test_activity_load_keeps_measured_when_rpe_agrees(self):
        # hrTSS 40 and RPE 4 -> sRPE 40 (ratio 1.0 < 1.5): no divergence, keep it.
        act = self._hr_activity(zone2_sec=3600, tss=40.0, rpe=4)
        self.assertAlmostEqual(load_math.activity_load(act), 40.0)


if __name__ == "__main__":
    unittest.main()
