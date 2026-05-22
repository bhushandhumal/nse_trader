import pytest
import pandas as pd

from src.data import _response_to_df, instrument_lookup


# ── _response_to_df ───────────────────────────────────────────────────────────

def _ohlcv_payload(ts_key='start_Time'):
    return {
        'status': 'success',
        'data': {
            'open':    [100.0, 101.0],
            'high':    [105.0, 106.0],
            'low':     [98.0,  99.0],
            'close':   [103.0, 104.0],
            'volume':  [1000,  2000],
            ts_key:    [1700000000, 1700000300],
        }
    }


class TestResponseToDf:
    def test_success_with_start_time_key(self):
        result = _response_to_df(_ohlcv_payload('start_Time'))
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == ['open', 'high', 'low', 'close', 'volume']
        assert len(result) == 2

    def test_success_with_timestamp_key(self):
        result = _response_to_df(_ohlcv_payload('timestamp'))
        assert len(result) == 2

    def test_index_is_datetime(self):
        result = _response_to_df(_ohlcv_payload())
        assert isinstance(result.index, pd.DatetimeIndex)
        assert result.index.name == 'date'

    def test_failure_status_raises_value_error(self):
        result = {'status': 'failure', 'data': '', 'remarks': {'error_code': 'DH-904'}}
        with pytest.raises(ValueError, match="Dhan API error"):
            _response_to_df(result)

    def test_non_dict_data_raises_value_error(self):
        result = {'status': 'success', 'data': 'No Records'}
        with pytest.raises(ValueError, match="Unexpected response format"):
            _response_to_df(result)

    def test_timestamps_converted_from_unix_seconds(self):
        result = _response_to_df(_ohlcv_payload())
        diff = (result.index[1] - result.index[0]).total_seconds()
        assert diff == 300  # 1700000300 - 1700000000


# ── instrument_lookup ─────────────────────────────────────────────────────────

class TestInstrumentLookup:
    def _make_df(self, symbol, exch, inst_name, sec_id):
        return pd.DataFrame([{
            'SEM_TRADING_SYMBOL':  symbol,
            'SEM_EXM_EXCH_ID':     exch,
            'SEM_INSTRUMENT_NAME': inst_name,
            'SEM_SMST_SECURITY_ID': sec_id,
        }])

    def test_returns_security_id_as_string(self):
        df = self._make_df('RELIANCE', 'NSE', 'EQUITY', 12345)
        assert instrument_lookup(df, 'RELIANCE') == '12345'

    def test_returns_none_for_unknown_symbol(self):
        df = self._make_df('RELIANCE', 'NSE', 'EQUITY', 12345)
        assert instrument_lookup(df, 'UNKNOWN') is None

    def test_filters_by_nse_only(self):
        df = self._make_df('RELIANCE', 'BSE', 'EQUITY', 99999)
        assert instrument_lookup(df, 'RELIANCE') is None

    def test_filters_by_equity_only(self):
        df = self._make_df('RELIANCE', 'NSE', 'FUTIDX', 99999)
        assert instrument_lookup(df, 'RELIANCE') is None
