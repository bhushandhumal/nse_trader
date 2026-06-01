import pytest


@pytest.fixture(autouse=True)
def _no_order_confirm_delay(monkeypatch):
    """Zero out the post-submission order-status poll delay so the suite doesn't
    sleep. Tests that exercise rejection set dhan.get_order_by_id explicitly."""
    monkeypatch.setattr('src.orders._CONFIRM_DELAY', 0)
