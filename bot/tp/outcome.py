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
    # Always present on both row stages ("trigger" and "final").
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
    total_volume: float
    realized_pnl: float
    bot_version: str
    # Trigger-only / optional fields.
    tp_trigger_price: float | None = None
    threshold_value: float | None = None
    threshold_unit: str | None = None
    move_at_trigger: float | None = None
    others_pnl: float | None = None
    partial_close_pct: int | None = None
    trailing_started: bool = False
    stop_loss: float | None = None
    risk_per_limit: float | None = None
    r_multiple: float | None = None
    risk_percent_cfg: float | None = None
    channel_id: int | None = None
    tp_strategy: str = "default"
    notes: dict | None = None
    # Two-stage analytics: "trigger" snapshot vs "final" settled result.
    stage: str = "trigger"
    mfe_price: float | None = None
    mfe_r: float | None = None
    mae_price: float | None = None
    mae_r: float | None = None
    level_sequence: int | None = None
    total_levels: int | None = None
    seconds_to_trigger: float | None = None
    hold_seconds: float | None = None
    exit_reason: str | None = None
