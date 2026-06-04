from dataclasses import dataclass


@dataclass
class TriggerSnapshot:
    """Runtime data captured at the moment TP fires.

    Strategy-internal: built inside execute(), consumed by TPEngine to assemble
    the full TPOutcome together with cross-cutting context (account, signal-level
    counts, config snapshot) the strategy doesn't see.
    """

    tp_trigger_price: float
    move_at_trigger: float
    realized_pnl: float
    others_pnl: float
    total_volume: float
    avg_entry_price: float
    partial_close_pct: int
    trailing_started: bool


@dataclass
class TPOutcome:
    signal_id: int
    mt5_account: int
    signal_type: str
    asset_class: str
    symbol: str
    direction: str
    total_limits: int
    limits_filled: int
    limits_pending: int
    limits_cancelled: int
    avg_entry_price: float
    tp_trigger_price: float
    threshold_value: float
    threshold_unit: str
    move_at_trigger: float
    realized_pnl: float
    others_pnl: float
    total_volume: float
    partial_close_pct: int
    trailing_started: bool
    bot_version: str
    stop_loss: float | None = None
    risk_per_limit: float | None = None
    r_multiple: float | None = None
    risk_percent_cfg: float | None = None
    channel_id: int | None = None
    tp_strategy: str = "default"
    notes: dict | None = None
