import datetime as dt

from main import _is_square_off_time


# A known weekday (2026-06-01 is a Monday) and weekend (2026-06-06 is a Saturday).
def _wd(h, m):
    return dt.datetime(2026, 6, 1, h, m)


def _weekend(h, m):
    return dt.datetime(2026, 6, 6, h, m)


class TestIsSquareOffTime:
    def test_before_square_off_is_false(self):
        assert _is_square_off_time(_wd(15, 14)) is False
        assert _is_square_off_time(_wd(9, 30)) is False

    def test_at_square_off_is_true(self):
        assert _is_square_off_time(_wd(15, 15)) is True

    def test_after_square_off_is_true(self):
        assert _is_square_off_time(_wd(15, 16)) is True
        assert _is_square_off_time(_wd(15, 29)) is True

    def test_weekend_is_false(self):
        assert _is_square_off_time(_weekend(15, 30)) is False
