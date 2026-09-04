"""
P1-FIX testleri — risk_manager.py update_peak kalicilik fix'i.

Kapsam:
  - update_peak artik HER cagrida kaydeder (yeni zirve olmasa bile)
  - is_circuit_broken / peak_equity state'i diske kalici yazilir
  - devre kesici trip/reset state machine'i restart sonrasi korunur
  - mevcut load-path testleri (test_risk_manager.py) kirilmaz
"""

import json
import os

from risk_manager import RiskManager


class TestUpdatePeakPersistence:
    def _read_state(self, path):
        with open(path) as f:
            return json.load(f)

    def test_update_peak_saves_even_without_new_peak(self, tmp_path):
        """P1-FIX: zirve yokken bile state diske yazilir."""
        state_file = str(tmp_path / "risk_state.json")
        rm = RiskManager(state_file=state_file, initial_equity=10000.0)
        # zirve 10000, bakiye 4111 -> yeni zirve YOK
        rm.update_peak(4111.0)
        assert rm.peak_equity == 10000.0  # zirve degismedi
        state = self._read_state(state_file)
        assert state["peak_equity"] == 10000.0
        assert state["is_circuit_broken"] is False

    def test_update_peak_raises_peak_and_saves(self, tmp_path):
        state_file = str(tmp_path / "risk_state.json")
        rm = RiskManager(state_file=state_file, initial_equity=10000.0)
        rm.update_peak(12000.0)
        assert rm.peak_equity == 12000.0
        state = self._read_state(state_file)
        assert state["peak_equity"] == 12000.0

    def test_circuit_breaker_state_persists_across_restart(self, tmp_path):
        """P1-FIX: DD buyukken trip state'i restart sonrasi korunur.

        Eski kod: update_peak yeni zirve olmadan kaydetmiyordu -> trip
        state'i diske hic yazilmiyordu -> restart'ta devre kesici
        'kapali' gorunuyordu (yanlis).
        """
        state_file = str(tmp_path / "risk_state.json")
        rm = RiskManager(state_file=state_file, initial_equity=10000.0)
        # DD %58.9 -> trip (>= %15)
        mult = rm.get_dynamic_risk_multiplier(4111.0, is_early_london=True)
        assert rm.is_circuit_broken is True
        assert mult == rm.base_risk_mult  # EL avantaji yok
        # trade kapanisi -> update_peak (yeni zirve yok, ama kaydetmeli)
        rm.update_peak(4111.0)
        state = self._read_state(state_file)
        assert state["is_circuit_broken"] is True
        # restart simule et
        rm2 = RiskManager(state_file=state_file, initial_equity=10000.0)
        assert rm2.is_circuit_broken is True
        assert rm2.peak_equity == 10000.0

    def test_reset_state_persists_across_restart(self, tmp_path):
        state_file = str(tmp_path / "risk_state.json")
        rm = RiskManager(state_file=state_file, initial_equity=10000.0)
        rm.update_peak(12000.0)  # zirve 12000
        rm.get_dynamic_risk_multiplier(9000.0, False)  # DD %25 -> trip
        assert rm.is_circuit_broken is True
        # DD %8 -> reset (<= %10)
        rm.get_dynamic_risk_multiplier(11040.0, False)
        assert rm.is_circuit_broken is False
        rm.update_peak(11040.0)
        state = self._read_state(state_file)
        assert state["is_circuit_broken"] is False
        rm2 = RiskManager(state_file=state_file, initial_equity=10000.0)
        assert rm2.is_circuit_broken is False

    def test_update_peak_after_trip_keeps_broken_flag(self, tmp_path):
        """Trip sonrasi update_peak cagrisi broken flag'i silmemeli."""
        state_file = str(tmp_path / "risk_state.json")
        rm = RiskManager(state_file=state_file, initial_equity=10000.0)
        rm.get_dynamic_risk_multiplier(8000.0, False)  # DD %20 -> trip
        assert rm.is_circuit_broken is True
        rm.update_peak(8000.0)  # zirve yok, ama state kaydedilmeli
        state = self._read_state(state_file)
        assert state["is_circuit_broken"] is True
        assert state["peak_equity"] == 10000.0

    def test_state_file_updated_on_every_call(self, tmp_path):
        """Her update_peak cagrisi dosya mtime'ini yeniler."""
        state_file = str(tmp_path / "risk_state.json")
        rm = RiskManager(state_file=state_file, initial_equity=10000.0)
        rm.update_peak(9000.0)
        mtime1 = os.path.getmtime(state_file)
        rm.update_peak(8500.0)
        mtime2 = os.path.getmtime(state_file)
        assert mtime2 >= mtime1
        state = self._read_state(state_file)
        assert state["peak_equity"] == 10000.0  # zirve hala 10000
