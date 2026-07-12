import logging
from datetime import UTC, datetime

from bot.config.constants import BOT_VERSION
from bot.config.settings import Settings
from bot.db.sqlite import SQLiteDB
from bot.db.tp_outcomes_writer import TPOutcomesWriter
from bot.mt5.client import MT5Client
from bot.tp.asset_config import get_config
from bot.tp.engine import _resolve_risk_percent
from bot.tp.outcome import TPOutcome
from bot.trading.lot_calculator import price_distance_to_money, resolve_lot_mode
from bot.trading.symbol_mapper import db_symbol_from_mt5, detect_asset_class

logger = logging.getLogger(__name__)


def _parse_utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


class TPFinalizer:
    """Writes the settled full-trade outcome (stage="final") once a signal's last
    position goes flat. Detection is an idempotent per-cycle sweep, so it catches
    every close path (TP full close, trailing stop, forced exit, SL hit)."""

    def __init__(self, writer: TPOutcomesWriter) -> None:
        self._writer = writer

    async def sweep(self, mt5_client: MT5Client, sqlite: SQLiteDB, config: Settings) -> None:
        signal_ids = await sqlite.get_settled_unfinalized_signals()
        if not signal_ids:
            return

        acct = mt5_client.account_info()
        now_iso = datetime.now(UTC).isoformat()

        for signal_id in signal_ids:
            # Claim first: only the call that inserts the guard row writes the outcome,
            # guaranteeing exactly one final row per signal.
            if not await sqlite.mark_signal_finalized(signal_id, now_iso):
                continue
            try:
                await self._record_final(signal_id, acct, mt5_client, sqlite, config)
            except Exception:
                logger.error("TP final outcome failed signal=%d", signal_id, exc_info=True)

    async def _record_final(
        self,
        signal_id: int,
        acct,
        mt5_client: MT5Client,
        sqlite: SQLiteDB,
        config: Settings,
    ) -> None:
        agg = await sqlite.get_signal_final_aggregate(signal_id)
        if agg is None or not agg["symbol"]:
            return
        summary = await sqlite.get_signal_summary(signal_id)

        mt5_symbol = agg["symbol"]
        db_sym = db_symbol_from_mt5(mt5_symbol, config)
        asset_class = detect_asset_class(db_sym)
        signal_type = agg["signal_type"] or "standard"
        asset_cfg = get_config(asset_class, signal_type, config, instrument=db_sym)

        total_volume = agg["total_volume"] or 0.0
        realized_pnl = agg["realized_pnl"] or 0.0
        stop_loss = agg["stop_loss"]
        avg_entry = (agg["entry_x_volume"] or 0.0) / total_volume if total_volume else 0.0
        risk_per_limit = (
            abs(avg_entry - float(stop_loss)) if stop_loss is not None and total_volume else None
        )

        sym_info = mt5_client.symbol_info(mt5_symbol)
        risk_money = (
            price_distance_to_money(sym_info, risk_per_limit, total_volume)
            if sym_info is not None and risk_per_limit
            else None
        )
        r_multiple = realized_pnl / risk_money if risk_money else None

        mfe_price = agg["mfe_price"]
        mae_price = agg["mae_price"]
        mfe_r = mfe_price / risk_per_limit if mfe_price is not None and risk_per_limit else None
        mae_r = mae_price / risk_per_limit if mae_price is not None and risk_per_limit else None

        any_trailing = bool(agg["any_trailing"])
        if any_trailing:
            exit_reason = "trailing_stop"
        elif realized_pnl < 0:
            exit_reason = "stop_loss"
        else:
            exit_reason = "tp_full"

        first_filled = _parse_utc(agg["first_filled_at"])
        last_closed = _parse_utc(agg["last_closed_at"])
        hold_seconds = (
            (last_closed - first_filled).total_seconds()
            if first_filled is not None and last_closed is not None
            else None
        )

        direction = "long" if (agg["order_type"] or "").startswith("buy") else "short"

        # Entry slippage in broker points, adverse-positive: longs filling above
        # the intended limit price are worse off; shorts mirrored.
        entry_slippage = None
        avg_fill = agg["avg_fill_price"]
        avg_intended = agg["avg_intended_price"]
        if avg_fill is not None and avg_intended is not None and sym_info and sym_info.point > 0:
            diff = avg_fill - avg_intended
            entry_slippage = (diff if direction == "long" else -diff) / sym_info.point

        # Resolved exit/lot config so trailing-vs-fixed analysis is not confounded
        # by per-user settings.
        notes = {
            "profit_threshold": asset_cfg.profit_threshold,
            "threshold_unit": asset_cfg.threshold_unit,
            "trailing_distance": asset_cfg.trailing_distance,
            "partial_close_percent": asset_cfg.partial_close_percent,
            "lot": resolve_lot_mode(config, mt5_symbol, signal_type, agg["channel_id"]),
            "disable_auto_tp": config.disable_auto_tp,
            "skip_limits_at": config.lot_sizing.skip_limits_at,
        }

        outcome = TPOutcome(
            signal_id=signal_id,
            mt5_account=acct.login if acct else 0,
            channel_id=agg["channel_id"],
            signal_type=signal_type,
            asset_class=asset_class.value,
            symbol=mt5_symbol,
            direction=direction,
            total_limits=summary["total"],
            limits_filled=summary["filled"] + summary["closed"],
            limits_pending=summary["pending"],
            limits_cancelled=summary["cancelled"],
            avg_entry_price=avg_entry,
            stop_loss=float(stop_loss) if stop_loss is not None else None,
            threshold_value=float(asset_cfg.profit_threshold),
            threshold_unit=asset_cfg.threshold_unit,
            realized_pnl=realized_pnl,
            total_volume=total_volume,
            trailing_started=any_trailing,
            risk_per_limit=risk_per_limit,
            r_multiple=r_multiple,
            risk_percent_cfg=_resolve_risk_percent(config, mt5_symbol),
            bot_version=BOT_VERSION,
            stage="final",
            mfe_price=mfe_price,
            mfe_r=mfe_r,
            mae_price=mae_price,
            mae_r=mae_r,
            level_sequence=agg["level_sequence"],
            total_levels=summary["total"],
            hold_seconds=hold_seconds,
            exit_reason=exit_reason,
            notes=notes,
            symbol_normalized=db_sym,
            account_equity=acct.equity if acct else None,
            account_balance=acct.balance if acct else None,
            entry_slippage_points=entry_slippage,
            exit_slippage_points=agg["avg_exit_slippage"],
        )
        await self._writer.record(outcome)
