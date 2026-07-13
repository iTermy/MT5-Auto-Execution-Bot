import json
import logging

from bot.db.queries import _TP_OUTCOME_COLUMNS, INSERT_TP_OUTCOME
from bot.db.supabase import SupabaseDB
from bot.tp.outcome import TPOutcome

logger = logging.getLogger(__name__)


class TPOutcomesWriter:
    def __init__(self, supabase: SupabaseDB) -> None:
        self._supabase = supabase

    async def record(self, outcome: TPOutcome) -> None:
        notes_json = json.dumps(outcome.notes) if outcome.notes is not None else None
        params = [
            notes_json if col == "notes" else getattr(outcome, col)
            for col in _TP_OUTCOME_COLUMNS
        ]
        try:
            async with self._supabase._pool.acquire() as conn:
                await conn.execute(INSERT_TP_OUTCOME, *params)
            logger.info(
                "TP outcome written signal=%d stage=%s pnl=%.2f",
                outcome.signal_id,
                outcome.stage,
                outcome.realized_pnl,
            )
        except Exception:
            logger.error("TP outcome write failed signal=%d", outcome.signal_id, exc_info=True)
