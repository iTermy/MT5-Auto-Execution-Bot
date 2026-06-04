import json
import logging

from bot.db.queries import INSERT_TP_OUTCOME
from bot.db.supabase import SupabaseDB
from bot.tp.outcome import TPOutcome

logger = logging.getLogger(__name__)


class TPOutcomesWriter:
    def __init__(self, supabase: SupabaseDB) -> None:
        self._supabase = supabase

    async def record(self, outcome: TPOutcome) -> None:
        notes_json = json.dumps(outcome.notes) if outcome.notes is not None else None
        try:
            async with self._supabase._pool.acquire() as conn:
                await conn.execute(
                    INSERT_TP_OUTCOME,
                    outcome.signal_id,
                    outcome.mt5_account,
                    outcome.channel_id,
                    outcome.signal_type,
                    outcome.asset_class,
                    outcome.symbol,
                    outcome.direction,
                    outcome.total_limits,
                    outcome.limits_filled,
                    outcome.limits_pending,
                    outcome.limits_cancelled,
                    outcome.avg_entry_price,
                    outcome.tp_trigger_price,
                    outcome.stop_loss,
                    outcome.threshold_value,
                    outcome.threshold_unit,
                    outcome.move_at_trigger,
                    outcome.realized_pnl,
                    outcome.others_pnl,
                    outcome.total_volume,
                    outcome.partial_close_pct,
                    outcome.trailing_started,
                    outcome.risk_per_limit,
                    outcome.r_multiple,
                    outcome.risk_percent_cfg,
                    outcome.bot_version,
                    outcome.tp_strategy,
                    notes_json,
                )
            logger.info(
                "TP outcome written signal=%d pnl=%.2f", outcome.signal_id, outcome.realized_pnl
            )
        except Exception:
            logger.error("TP outcome write failed signal=%d", outcome.signal_id, exc_info=True)
