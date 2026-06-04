from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config.constants import BOT_VERSION
from bot.db.tp_outcomes_writer import TPOutcomesWriter
from bot.tp.outcome import TPOutcome


def _outcome(**overrides) -> TPOutcome:
    base = dict(
        signal_id=2079,
        mt5_account=123456,
        signal_type="standard",
        asset_class="metals",
        symbol="XAUUSD",
        direction="long",
        total_limits=4,
        limits_filled=3,
        limits_pending=0,
        limits_cancelled=1,
        avg_entry_price=4459.0,
        tp_trigger_price=4463.1,
        threshold_value=5.0,
        threshold_unit="dollars",
        move_at_trigger=5.24,
        realized_pnl=71.1,
        others_pnl=24.7,
        total_volume=0.3,
        partial_close_pct=50,
        trailing_started=True,
        bot_version=BOT_VERSION,
        stop_loss=4440.0,
        risk_per_limit=19.0,
        risk_percent_cfg=1.0,
        channel_id=99,
    )
    base.update(overrides)
    return TPOutcome(**base)


@pytest.mark.asyncio
async def test_record_calls_insert_with_all_fields() -> None:
    conn = AsyncMock()
    pool_cm = MagicMock()
    pool_cm.__aenter__ = AsyncMock(return_value=conn)
    pool_cm.__aexit__ = AsyncMock(return_value=None)
    supabase = MagicMock()
    supabase._pool = MagicMock()
    supabase._pool.acquire = MagicMock(return_value=pool_cm)

    writer = TPOutcomesWriter(supabase)
    await writer.record(_outcome())

    conn.execute.assert_awaited_once()
    args = conn.execute.await_args.args
    # 1st arg is the SQL, then 28 positional params
    assert len(args) == 29
    assert args[1] == 2079  # signal_id
    assert args[2] == 123456  # mt5_account
    assert args[6] == "XAUUSD"  # symbol


@pytest.mark.asyncio
async def test_record_swallows_exception() -> None:
    supabase = MagicMock()
    supabase._pool = MagicMock()
    supabase._pool.acquire = MagicMock(side_effect=RuntimeError("pool down"))

    writer = TPOutcomesWriter(supabase)
    # Should not raise — bot must never crash due to analytics failures
    await writer.record(_outcome())
