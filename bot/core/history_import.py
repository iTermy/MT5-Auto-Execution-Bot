from collections import defaultdict
from datetime import UTC, datetime
from math import isclose

from bot.config.constants import MAGIC_NUMBER
from bot.core.reconciler import _parse_comment


def history_rows(deals: list) -> tuple[list[tuple], int]:
    positions = defaultdict(list)
    for deal in deals:
        if deal.position_id:
            positions[deal.position_id].append(deal)
    rows = []
    skipped = 0
    for position_id, group in positions.items():
        entries = [d for d in group if d.entry == 0 and d.type in (0, 1)]
        if not any(d.magic == MAGIC_NUMBER for d in entries):
            continue
        exits = [d for d in group if d.entry in (1, 3) and d.type in (0, 1)]
        volume = sum(d.volume for d in entries)
        # Incomplete history and netting/reversal positions cannot be reconstructed safely.
        if (
            any(d.magic != MAGIC_NUMBER for d in entries)
            or any(d.entry == 2 for d in group)
            or not exits
            or not isclose(volume, sum(d.volume for d in exits), abs_tol=1e-8)
        ):
            skipped += 1
            continue
        first = min(entries, key=lambda d: d.time)
        parsed = _parse_comment(first.comment)
        signal_id, limit_id = parsed if parsed else (-position_id, None)
        opened = datetime.fromtimestamp(first.time, UTC).isoformat()
        closed = datetime.fromtimestamp(max(d.time for d in exits), UTC).isoformat()
        pnl = sum(d.profit + d.commission + d.swap + d.fee for d in group)
        rows.append(
            (
                position_id,
                limit_id,
                signal_id,
                first.symbol,
                "buy" if first.type == 0 else "sell",
                volume,
                opened,
                opened,
                closed,
                pnl,
            )
        )
    return rows, skipped
