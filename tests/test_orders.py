import logging
import pytest
from unittest.mock import MagicMock, call

from src.orders import place_market_order, place_sl_order, modify_sl_order, square_off_all


@pytest.fixture
def dhan():
    return MagicMock()


# ── place_market_order ────────────────────────────────────────────────────────

class TestPlaceMarketOrder:
    def test_dry_run_logs_and_returns_none(self, dhan, caplog):
        with caplog.at_level(logging.INFO):
            result = place_market_order(dhan, '12345', 'buy', 10, dry_run=True)
        assert result is None
        assert '[DRY RUN]' in caplog.text
        assert 'buy' in caplog.text

    def test_dry_run_does_not_call_api(self, dhan):
        place_market_order(dhan, '12345', 'buy', 10, dry_run=True)
        dhan.place_order.assert_not_called()

    def test_live_calls_place_order(self, dhan):
        dhan.place_order.return_value = {'status': 'success', 'data': {'orderId': 'ORD1'}}
        place_market_order(dhan, '12345', 'buy', 10, dry_run=False)
        dhan.place_order.assert_called_once()

    def test_live_exception_returns_none(self, dhan):
        dhan.place_order.side_effect = Exception("API down")
        result = place_market_order(dhan, '12345', 'buy', 10, dry_run=False)
        assert result is None


# ── place_sl_order ────────────────────────────────────────────────────────────

class TestPlaceSlOrder:
    def test_dry_run_logs_and_no_api_call(self, dhan, caplog):
        with caplog.at_level(logging.INFO):
            place_sl_order(dhan, '12345', 'buy', 10, 1400.0, dry_run=True)
        assert '[DRY RUN]' in caplog.text
        assert '1400' in caplog.text
        dhan.place_order.assert_not_called()

    def test_live_places_entry_then_sl(self, dhan):
        dhan.place_order.return_value = {'status': 'success', 'data': {'orderId': 'ORD1'}}
        place_sl_order(dhan, '12345', 'buy', 10, 1400.0, dry_run=False)
        assert dhan.place_order.call_count == 2

    def test_live_skips_sl_if_entry_rejected(self, dhan, caplog):
        dhan.place_order.return_value = {'status': 'failure', 'data': {}}
        with caplog.at_level(logging.ERROR):
            place_sl_order(dhan, '12345', 'buy', 10, 1400.0, dry_run=False)
        assert dhan.place_order.call_count == 1
        assert 'SL order NOT placed' in caplog.text

    def test_buy_uses_correct_sl_side(self, dhan):
        dhan.place_order.return_value = {'status': 'success', 'data': {'orderId': 'ORD1'}}
        place_sl_order(dhan, '12345', 'buy', 10, 1400.0, dry_run=False)
        # Entry = BUY, SL = SELL
        entry_call, sl_call = dhan.place_order.call_args_list
        assert entry_call.kwargs['transaction_type'] == dhan.BUY
        assert sl_call.kwargs['transaction_type'] == dhan.SELL

    def test_sell_uses_correct_sl_side(self, dhan):
        dhan.place_order.return_value = {'status': 'success', 'data': {'orderId': 'ORD1'}}
        place_sl_order(dhan, '12345', 'sell', 10, 1600.0, dry_run=False)
        entry_call, sl_call = dhan.place_order.call_args_list
        assert entry_call.kwargs['transaction_type'] == dhan.SELL
        assert sl_call.kwargs['transaction_type'] == dhan.BUY

    def test_dry_run_returns_none(self, dhan):
        result = place_sl_order(dhan, '12345', 'buy', 10, 1400.0, dry_run=True)
        assert result is None

    def test_successful_order_returns_order_id(self, dhan):
        dhan.place_order.return_value = {'status': 'success', 'data': {'orderId': 'ORD42'}}
        result = place_sl_order(dhan, '12345', 'buy', 10, 1400.0, dry_run=False)
        assert result == 'ORD42'

    def test_entry_rejection_returns_none(self, dhan):
        dhan.place_order.return_value = {'status': 'failure', 'data': {}}
        result = place_sl_order(dhan, '12345', 'buy', 10, 1400.0, dry_run=False)
        assert result is None


# ── modify_sl_order ───────────────────────────────────────────────────────────

class TestModifySlOrder:
    def test_dry_run_logs_and_no_api_call(self, dhan, caplog):
        with caplog.at_level(logging.INFO):
            modify_sl_order(dhan, 'ORD1', 10, 1350.0, dry_run=True)
        assert '[DRY RUN]' in caplog.text
        assert 'ORD1' in caplog.text
        dhan.modify_order.assert_not_called()

    def test_live_calls_modify_order(self, dhan):
        modify_sl_order(dhan, 'ORD1', 10, 1350.0, dry_run=False)
        dhan.modify_order.assert_called_once()
        call_kwargs = dhan.modify_order.call_args.kwargs
        assert call_kwargs['order_id'] == 'ORD1'
        assert call_kwargs['price'] == 1350.0
        assert call_kwargs['trigger_price'] == 1350.0


# ── square_off_all ────────────────────────────────────────────────────────────

class TestSquareOffAll:
    def _setup_dhan(self, dhan, orders=None, positions=None):
        dhan.get_order_list.return_value = {'data': orders or []}
        dhan.get_positions.return_value  = {'data': positions or []}

    def test_dry_run_cancels_pending_orders_in_log(self, dhan, caplog):
        self._setup_dhan(dhan, orders=[
            {'orderId': 'ORD1', 'orderStatus': 'PENDING', 'productType': 'INTRA', 'tradingSymbol': 'RELIANCE'},
            {'orderId': 'ORD2', 'orderStatus': 'TRANSIT', 'productType': 'INTRA', 'tradingSymbol': 'INFY'},
        ])
        with caplog.at_level(logging.INFO):
            square_off_all(dhan, dry_run=True)
        assert '[DRY RUN]' in caplog.text
        assert 'ORD1' in caplog.text
        assert 'ORD2' in caplog.text
        dhan.cancel_order.assert_not_called()

    def test_dry_run_squares_off_positions_in_log(self, dhan, caplog):
        self._setup_dhan(dhan, positions=[
            {'netQty': 5,  'tradingSymbol': 'RELIANCE', 'securityId': '12345'},
            {'netQty': -3, 'tradingSymbol': 'INFY',     'securityId': '67890'},
        ])
        with caplog.at_level(logging.INFO):
            square_off_all(dhan, dry_run=True)
        assert 'RELIANCE' in caplog.text
        assert 'INFY' in caplog.text
        dhan.place_order.assert_not_called()

    def test_skips_non_intra_orders(self, dhan, caplog):
        self._setup_dhan(dhan, orders=[
            {'orderId': 'ORD1', 'orderStatus': 'PENDING', 'productType': 'CNC', 'tradingSymbol': 'TCS'},
        ])
        with caplog.at_level(logging.INFO):
            square_off_all(dhan, dry_run=True)
        assert 'ORD1' not in caplog.text

    def test_skips_zero_qty_positions(self, dhan):
        self._setup_dhan(dhan, positions=[
            {'netQty': 0, 'tradingSymbol': 'RELIANCE', 'securityId': '12345'},
        ])
        square_off_all(dhan, dry_run=True)
        dhan.place_order.assert_not_called()

    def test_handles_order_fetch_failure_gracefully(self, dhan):
        dhan.get_order_list.side_effect = Exception("network error")
        dhan.get_positions.return_value = {'data': []}
        square_off_all(dhan, dry_run=True)  # should not raise
