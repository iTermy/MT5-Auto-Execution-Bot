from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from bot.mt5.client import MT5Client
from bot.mt5.types import RateInfo, TickInfo
from bot.trading.offset_calculator import OffsetCalculator
from tests.conftest import make_tick

# Pin "server == UTC" so target_epoch == updated_at epoch and history windows are
# easy to reason about. ref tick .time is server epoch; with time.time() ~= now the
# derived server_offset rounds to 0.


def _client(**overrides) -> MagicMock:
    c = MagicMock(spec=MT5Client)
    c.symbol_info_tick.return_value = make_tick(
        bid=4600.0, ask=4602.0, time=int(datetime.now(UTC).timestamp())
    )
    c.copy_ticks_range.return_value = []
    c.copy_rates_range.return_value = []
    for k, v in overrides.items():
        getattr(c, k).return_value = v
    return c


def _row(bid: float, ask: float, age_seconds: float) -> dict:
    return {
        "bid": bid,
        "ask": ask,
        "updated_at": datetime.now(UTC) - timedelta(seconds=age_seconds),
    }


def test_fresh_feed_uses_live_tick() -> None:
    # Feed written seconds ago → pair with the current tick, no history call.
    calc = OffsetCalculator()
    client = _client()
    client.symbol_info_tick.return_value = make_tick(bid=4610.0, ask=4612.0)
    offset = calc.get_offset("US500", _row(4600.0, 4601.0, age_seconds=5), client, 3600)
    assert offset == (4611.0 - 4600.5)
    client.copy_ticks_range.assert_not_called()


def test_old_feed_uses_timestamp_matched_history() -> None:
    # Feed 10 min old → look up the broker tick at updated_at, not the live tick.
    calc = OffsetCalculator()
    row = _row(4600.0, 4601.0, age_seconds=600)
    target = row["updated_at"].timestamp()
    ticks = [
        TickInfo(symbol="US500", bid=4598.0, ask=4600.0, time=int(target - 30)),
        TickInfo(symbol="US500", bid=4620.0, ask=4622.0, time=int(target)),  # closest
    ]
    client = _client()
    client.copy_ticks_range.return_value = ticks
    offset = calc.get_offset("US500", row, client, 3600)
    assert offset == (4621.0 - 4600.5)
    client.copy_ticks_range.assert_called_once()


def test_m1_fallback_when_no_ticks() -> None:
    calc = OffsetCalculator()
    row = _row(4600.0, 4601.0, age_seconds=600)
    target = row["updated_at"].timestamp()
    client = _client()
    client.copy_ticks_range.return_value = []
    client.copy_rates_range.return_value = [RateInfo(time=int(target), open=4618.0, close=4622.0)]
    offset = calc.get_offset("US500", row, client, 3600)
    assert offset == (4620.0 - 4600.5)


def test_skips_when_no_history() -> None:
    calc = OffsetCalculator()
    client = _client()  # both tick-range and rate-range empty
    assert calc.get_offset("US500", _row(4600.0, 4601.0, age_seconds=600), client, 3600) is None


def test_dead_feed_beyond_bound_skipped() -> None:
    calc = OffsetCalculator()
    client = _client()
    # 2h old, bound 1h → dead feed, skip without any history lookup.
    assert calc.get_offset("US500", _row(4600.0, 4601.0, age_seconds=7200), client, 3600) is None
    client.copy_ticks_range.assert_not_called()


def test_idle_feed_served_from_cache_no_repeat_history() -> None:
    # Frozen updated_at over many cycles → exactly one history lookup, then cache.
    calc = OffsetCalculator()
    row = _row(4600.0, 4601.0, age_seconds=600)
    target = row["updated_at"].timestamp()
    client = _client()
    client.copy_ticks_range.return_value = [
        TickInfo(symbol="US500", bid=4620.0, ask=4622.0, time=int(target))
    ]
    first = calc.get_offset("US500", row, client, 3600)
    for _ in range(10):
        again = calc.get_offset("US500", row, client, 3600)
        assert again == first
    client.copy_ticks_range.assert_called_once()


def test_new_feed_row_recomputes() -> None:
    calc = OffsetCalculator()
    client = _client()
    target1 = (datetime.now(UTC) - timedelta(seconds=600)).timestamp()
    row1 = _row(4600.0, 4601.0, age_seconds=600)
    client.copy_ticks_range.return_value = [
        TickInfo(symbol="US500", bid=4620.0, ask=4622.0, time=int(row1["updated_at"].timestamp()))
    ]
    calc.get_offset("US500", row1, client, 3600)
    row2 = _row(4605.0, 4606.0, age_seconds=600)
    client.copy_ticks_range.return_value = [
        TickInfo(symbol="US500", bid=4630.0, ask=4632.0, time=int(row2["updated_at"].timestamp()))
    ]
    offset2 = calc.get_offset("US500", row2, client, 3600)
    assert offset2 == (4631.0 - 4605.5)
    assert client.copy_ticks_range.call_count == 2
    _ = target1


def test_check_drift() -> None:
    calc = OffsetCalculator()
    assert calc.check_drift(100.0, 90.0, 5.0) is True
    assert calc.check_drift(92.0, 90.0, 5.0) is False
