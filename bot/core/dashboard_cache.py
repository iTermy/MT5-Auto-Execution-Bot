import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class DashboardData:
    account: dict = field(default_factory=dict)
    positions: list[dict] = field(default_factory=list)
    pending_orders: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=lambda: {
        "total_profit": 0.0,
        "open_count": 0,
        "pending_count": 0,
        "trailing_count": 0,
    })
    updated_at: str = ""


class DashboardCache:
    def __init__(self) -> None:
        self._data = DashboardData()

    @property
    def data(self) -> DashboardData:
        return self._data

    def update(self, account_info, mt5_positions, mt5_orders, sqlite_active, mt5_client) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()

        sqlite_by_ticket = {r["mt5_ticket"]: r for r in sqlite_active}

        acct = {}
        if account_info:
            acct = {
                "login": account_info.login,
                "balance": account_info.balance,
                "equity": account_info.equity,
                "margin": account_info.margin,
                "margin_free": account_info.margin_free,
                "leverage": account_info.leverage,
                "currency": account_info.currency,
            }

        positions = []
        for pos in mt5_positions:
            row = sqlite_by_ticket.get(pos.ticket)
            current_price = pos.price_open
            tick = mt5_client.symbol_info_tick(pos.symbol)
            if tick:
                current_price = tick.bid if pos.type == 0 else tick.ask
            positions.append({
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "direction": "long" if pos.type == 0 else "short",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "current_price": current_price,
                "sl": pos.sl,
                "profit": pos.profit,
                "is_trailing": bool(row["is_trailing"]) if row else False,
                "signal_id": row["signal_id"] if row else 0,
            })

        pending = []
        for order in mt5_orders:
            row = sqlite_by_ticket.get(order.ticket)
            current_price = 0.0
            distance = 0.0
            tick = mt5_client.symbol_info_tick(order.symbol)
            if tick:
                mid = (tick.bid + tick.ask) / 2
                current_price = mid
                distance = abs(order.price_open - mid)
            pending.append({
                "ticket": order.ticket,
                "symbol": order.symbol,
                "direction": "long" if order.type in (2, 4) else "short",
                "volume": order.volume_current,
                "price_level": order.price_open,
                "current_price": current_price,
                "sl": order.sl,
                "distance": round(distance, 5),
                "signal_id": row["signal_id"] if row else 0,
            })

        total_profit = sum(p["profit"] for p in positions)
        trailing_count = sum(1 for p in positions if p["is_trailing"])

        self._data = DashboardData(
            account=acct,
            positions=positions,
            pending_orders=pending,
            summary={
                "total_profit": round(total_profit, 2),
                "open_count": len(positions),
                "pending_count": len(pending),
                "trailing_count": trailing_count,
            },
            updated_at=now_iso,
        )
