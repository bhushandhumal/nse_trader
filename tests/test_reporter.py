import pytest
from unittest.mock import MagicMock

from src.reporter import print_eod_report


@pytest.fixture
def dhan():
    m = MagicMock()
    m.get_positions.return_value = {'data': []}
    return m


def _make_state(trades=None):
    return {
        'st_dir':       {},
        'prev_signals': {},
        'trades':       trades or [],
    }


def _make_trade(ticker='BHEL', action='buy', qty=100, sl=402.0, order_id='ORD1', time='09:32'):
    return {'ticker': ticker, 'action': action, 'qty': qty,
            'sl_price': sl, 'order_id': order_id, 'time': time}


# ── no trades ─────────────────────────────────────────────────────────────────

def test_no_trades_prints_no_trades_message(dhan, capsys):
    print_eod_report('Test Strategy', _make_state(), dhan)
    out = capsys.readouterr().out
    assert 'No trades placed today' in out


def test_no_trades_does_not_fetch_positions(dhan, capsys):
    print_eod_report('Test Strategy', _make_state(), dhan)
    dhan.get_positions.assert_not_called()


# ── trade table ───────────────────────────────────────────────────────────────

def test_trade_table_shows_ticker_and_side(dhan, capsys):
    state = _make_state([_make_trade('BHEL', 'buy')])
    print_eod_report('Test Strategy', state, dhan)
    out = capsys.readouterr().out
    assert 'BHEL' in out
    assert 'BUY' in out


def test_trade_table_shows_sl_price(dhan, capsys):
    state = _make_state([_make_trade(sl=402.5)])
    print_eod_report('Test Strategy', state, dhan)
    out = capsys.readouterr().out
    assert '402.5' in out


def test_trade_table_shows_order_id(dhan, capsys):
    state = _make_state([_make_trade(order_id='ORD99')])
    print_eod_report('Test Strategy', state, dhan)
    out = capsys.readouterr().out
    assert 'ORD99' in out


def test_dry_run_trade_shows_dry_run_label(dhan, capsys):
    state = _make_state([_make_trade(order_id=None)])
    print_eod_report('Test Strategy', state, dhan)
    out = capsys.readouterr().out
    assert 'DRY RUN' in out


def test_multiple_trades_all_shown(dhan, capsys):
    trades = [
        _make_trade('BHEL', 'buy',  100, order_id='ORD1'),
        _make_trade('SBIN', 'sell', 50,  order_id='ORD2'),
    ]
    print_eod_report('Test Strategy', _make_state(trades), dhan)
    out = capsys.readouterr().out
    assert 'BHEL' in out
    assert 'SBIN' in out


# ── P&L section ───────────────────────────────────────────────────────────────

def test_pnl_section_shows_realized_and_unrealized(dhan, capsys):
    dhan.get_positions.return_value = {'data': [
        {'tradingSymbol': 'BHEL', 'netQty': 0,
         'realizedProfit': -620.0, 'unrealizedProfit': 0.0},
    ]}
    state = _make_state([_make_trade('BHEL')])
    print_eod_report('Test Strategy', state, dhan)
    out = capsys.readouterr().out
    assert '-620' in out
    assert 'Realized' in out
    assert 'Net P&L' in out


def test_pnl_only_shows_traded_tickers(dhan, capsys):
    dhan.get_positions.return_value = {'data': [
        {'tradingSymbol': 'BHEL', 'netQty': 0,
         'realizedProfit': -620.0, 'unrealizedProfit': 0.0},
        {'tradingSymbol': 'INFY', 'netQty': 10,   # traded by another strategy
         'realizedProfit': 1000.0, 'unrealizedProfit': 200.0},
    ]}
    state = _make_state([_make_trade('BHEL')])  # only BHEL traded by this strategy
    print_eod_report('Test Strategy', state, dhan)
    out = capsys.readouterr().out
    assert 'BHEL' in out
    assert 'INFY' not in out


def test_net_pnl_is_sum_of_realized_and_unrealized(dhan, capsys):
    dhan.get_positions.return_value = {'data': [
        {'tradingSymbol': 'BHEL', 'netQty': 50,
         'realizedProfit': 300.0, 'unrealizedProfit': 150.0},
    ]}
    state = _make_state([_make_trade('BHEL')])
    print_eod_report('Test Strategy', state, dhan)
    out = capsys.readouterr().out
    assert '450' in out   # 300 + 150


def test_position_fetch_failure_does_not_raise(dhan, capsys):
    dhan.get_positions.side_effect = Exception("API timeout")
    state = _make_state([_make_trade('BHEL')])
    print_eod_report('Test Strategy', state, dhan)  # should not raise
    out = capsys.readouterr().out
    assert 'BHEL' in out   # trade table still printed


def test_no_matching_positions_prints_trade_count(dhan, capsys):
    dhan.get_positions.return_value = {'data': []}
    state = _make_state([_make_trade('BHEL'), _make_trade('SBIN')])
    print_eod_report('Test Strategy', state, dhan)
    out = capsys.readouterr().out
    assert 'Trades placed: 2' in out


# ── strategy name and header ──────────────────────────────────────────────────

def test_report_header_contains_strategy_name(dhan, capsys):
    print_eod_report('Three Supertrends', _make_state([_make_trade()]), dhan)
    out = capsys.readouterr().out
    assert 'Three Supertrends' in out
