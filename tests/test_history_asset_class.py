from types import SimpleNamespace

from bot.api.routes import get_history
from tests.conftest import make_settings


async def _insert_closed(sqlite_db, *, limit_id, signal_id, ticket, symbol, pnl) -> None:
    await sqlite_db.insert_order(
        limit_id=limit_id,
        signal_id=signal_id,
        mt5_ticket=ticket,
        order_type="buy_limit",
        lot_size=0.10,
        placed_at="2026-06-01T10:00:00+00:00",
        db_stop_loss=1.0,
        signal_type="standard",
        symbol=symbol,
    )
    await sqlite_db.mark_filled(ticket, "2026-06-01T11:00:00+00:00")
    await sqlite_db.mark_closed(ticket, pnl)


def _request(sqlite_db, config):
    engine = SimpleNamespace(sqlite=sqlite_db, config=config)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))


async def test_history_resolves_asset_class_through_symbol_map(sqlite_db) -> None:
    """order_mappings.symbol is the *broker* symbol, so the class must be resolved
    against symbol_map/stock_suffix. Each case here is one the frontend's own
    classifier got wrong when it was handed the broker symbol directly: BTCUSD is
    6 chars so its length test misses crypto, AMD.NAS-24 loses the '.NAS' suffix
    match and then hits the 'NAS' index keyword, and XTIUSD reads as plain forex."""
    config = make_settings(
        symbol_map={"BTCUSDT": "BTCUSD", "USOILSPOT": "XTIUSD", "SPX500USD": "US500"},
        stock_suffix="-24",
    )
    cases = [
        ("BTCUSD", "crypto"),
        ("AMD.NAS-24", "stocks"),
        ("XTIUSD", "oil"),
        ("US500", "indices"),
        ("XAUUSD", "metals"),
        ("USDJPY", "forex_jpy"),
        ("EURUSD", "forex"),
    ]
    for i, (symbol, _) in enumerate(cases, start=1):
        await _insert_closed(
            sqlite_db, limit_id=i, signal_id=i, ticket=1000 + i, symbol=symbol, pnl=1.0
        )

    result = await get_history(_request(sqlite_db, config))

    by_symbol = {t["symbol"]: t["asset_class"] for t in result["trades"]}
    assert by_symbol == dict(cases)
