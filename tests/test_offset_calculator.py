from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from bot.mt5.client import MT5Client
from bot.mt5.types import RateInfo, TickInfo
from bot.trading.offset_calculator import OffsetCalculator
from tests.conftest import make_tick

# Pin "server == UTC" so target_epoch == updated_at epoch and history windows are
# easy to reason about. The ref tick .time is the server epoch; with time.time() ~=
# now the derived server_offset rounds to 0. A large recompute interval keeps each
# call independent unless a test explicitly probes the throttle.

_INTERVAL = 300


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


def _tick(updated_at: datetime, bid: float, ask: float, offset_ms: int = 0) -> TickInfo:
    epoch_ms = int(updated_at.timestamp() * 1000) + offset_ms
    return TickInfo(
        symbol="US500", bid=bid, ask=ask, time=epoch_ms // 1000, time_msc=epoch_ms
    )


def test_offset_matched_to_updated_at() -> None:
    # Broker mid at the feed's exact updated_at minus the feed mid.
    calc = OffsetCalculator()
    row = _row(4600.0, 4601.0, age_seconds=2)
    client = _client()
    client.copy_ticks_range.return_value = [_tick(row["updated_at"], 4620.0, 4622.0)]
    offset = calc.get_offset("US500", row, client, 120, _INTERVAL)
    assert offset == (4621.0 - 4600.5)


def test_picks_closest_tick_to_the_millisecond() -> None:
    # Several ticks around updated_at → the one nearest in time_msc is used, even a
    # second on either side.
    calc = OffsetCalculator()
    row = _row(4600.0, 4601.0, age_seconds=2)
    client = _client()
    client.copy_ticks_range.return_value = [
        _tick(row["updated_at"], 4598.0, 4600.0, offset_ms=-1200),
        _tick(row["updated_at"], 4620.0, 4622.0, offset_ms=-50),  # closest
        _tick(row["updated_at"], 4640.0, 4642.0, offset_ms=900),
    ]
    offset = calc.get_offset("US500", row, client, 120, _INTERVAL)
    assert offset == (4621.0 - 4600.5)


def test_m1_fallback_when_no_ticks() -> None:
    calc = OffsetCalculator()
    row = _row(4600.0, 4601.0, age_seconds=60)
    target = row["updated_at"].timestamp()
    client = _client()
    client.copy_ticks_range.return_value = []
    client.copy_rates_range.return_value = [RateInfo(time=int(target), open=4618.0, close=4622.0)]
    offset = calc.get_offset("US500", row, client, 120, _INTERVAL)
    assert offset == (4620.0 - 4600.5)


def test_skips_when_no_history_and_no_cache() -> None:
    calc = OffsetCalculator()
    client = _client()  # both tick-range and rate-range empty
    assert calc.get_offset("US500", _row(4600.0, 4601.0, age_seconds=60), client, 120, _INTERVAL) is None


def test_dead_feed_beyond_bound_skipped() -> None:
    calc = OffsetCalculator()
    client = _client()
    # 5min old, bound 2min → stalled feed, skip without any history lookup.
    assert calc.get_offset("US500", _row(4600.0, 4601.0, age_seconds=300), client, 120, _INTERVAL) is None
    client.copy_ticks_range.assert_not_called()


def test_recompute_throttled_to_interval() -> None:
    # Within the recompute interval the cached offset is served and no MT5 history
    # call is repeated, even as the feed row keeps changing.
    calc = OffsetCalculator()
    row1 = _row(4600.0, 4601.0, age_seconds=10)
    client = _client()
    client.copy_ticks_range.return_value = [_tick(row1["updated_at"], 4620.0, 4622.0)]
    first = calc.get_offset("US500", row1, client, 120, _INTERVAL)
    for _ in range(10):
        again = calc.get_offset("US500", _row(4605.0, 4606.0, age_seconds=5), client, 120, _INTERVAL)
        assert again == first
    client.copy_ticks_range.assert_called_once()


def test_recomputes_after_interval_elapses() -> None:
    # A zero interval forces recomputation on every call.
    calc = OffsetCalculator()
    row1 = _row(4600.0, 4601.0, age_seconds=10)
    client = _client()
    client.copy_ticks_range.return_value = [_tick(row1["updated_at"], 4620.0, 4622.0)]
    calc.get_offset("US500", row1, client, 120, 0)
    row2 = _row(4605.0, 4606.0, age_seconds=10)
    client.copy_ticks_range.return_value = [_tick(row2["updated_at"], 4630.0, 4632.0)]
    offset2 = calc.get_offset("US500", row2, client, 120, 0)
    assert offset2 == (4631.0 - 4605.5)
    assert client.copy_ticks_range.call_count == 2


def test_history_gap_serves_cached_offset() -> None:
    # Once cached, a transient history gap returns the last good offset, not None.
    calc = OffsetCalculator()
    row1 = _row(4600.0, 4601.0, age_seconds=10)
    client = _client()
    client.copy_ticks_range.return_value = [_tick(row1["updated_at"], 4620.0, 4622.0)]
    first = calc.get_offset("US500", row1, client, 120, 0)
    client.copy_ticks_range.return_value = []
    client.copy_rates_range.return_value = []
    again = calc.get_offset("US500", _row(4605.0, 4606.0, age_seconds=10), client, 120, 0)
    assert again == first


def test_check_drift() -> None:
    calc = OffsetCalculator()
    assert calc.check_drift(100.0, 90.0, 5.0) is True
    assert calc.check_drift(92.0, 90.0, 5.0) is False
