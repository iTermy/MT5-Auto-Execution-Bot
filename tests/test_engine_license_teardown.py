from bot.core.engine import Engine
from bot.license.models import LicenseStatus
from bot.license.validator import LicenseValidator

# --- Engine teardown decision (armed flip + confirmed rejection) ---


def test_not_confirmed_rejected_does_not_teardown() -> None:
    # Covers both a transient ERROR and a single sub-threshold rejection: the validator
    # reports confirmed_rejected=False, so positions stay put and the engine stays armed
    # for a later genuine rejection.
    armed, teardown = Engine._teardown_decision(True, False, False)
    assert teardown is False
    assert armed is True


def test_sustained_rejection_tears_down() -> None:
    armed, teardown = Engine._teardown_decision(True, False, True)
    assert teardown is True
    assert armed is False


def test_valid_rearms() -> None:
    armed, teardown = Engine._teardown_decision(False, True, False)
    assert teardown is False
    assert armed is True


def test_rejection_while_disarmed_does_not_teardown() -> None:
    # A license invalid from startup (never armed) must not teardown.
    armed, teardown = Engine._teardown_decision(False, False, True)
    assert teardown is False
    assert armed is False


# --- Validator rejection streak (_next_streak) ---


def test_streak_requires_consecutive_rejections() -> None:
    streak, rejected = LicenseValidator._next_streak(0, 2, LicenseStatus.INVALID)
    assert (streak, rejected) == (1, False)
    streak, rejected = LicenseValidator._next_streak(streak, 2, LicenseStatus.INVALID)
    assert (streak, rejected) == (2, True)


def test_expired_counts_toward_streak() -> None:
    streak, rejected = LicenseValidator._next_streak(1, 2, LicenseStatus.EXPIRED)
    assert (streak, rejected) == (2, True)


def test_valid_resets_streak() -> None:
    streak, rejected = LicenseValidator._next_streak(1, 2, LicenseStatus.VALID)
    assert (streak, rejected) == (0, False)


def test_error_leaves_streak_untouched() -> None:
    # A transient ERROR mid-streak neither advances nor clears it.
    streak, rejected = LicenseValidator._next_streak(1, 2, LicenseStatus.ERROR)
    assert (streak, rejected) == (1, False)


def test_error_does_not_break_a_completed_streak() -> None:
    streak, rejected = LicenseValidator._next_streak(2, 2, LicenseStatus.ERROR)
    assert (streak, rejected) == (2, True)


# --- End-to-end: validator streak feeding the engine teardown/placement gate ---


class _Sim:
    """Composes the two real pure functions exactly as the engine wires them, so a
    sequence of license statuses produces (placement_active, teardown). placement_active
    mirrors the engine: it tracks the armed flag (`_last_license_valid`)."""

    def __init__(self, armed_at_startup: bool, threshold: int = 2) -> None:
        self.armed = armed_at_startup
        self.threshold = threshold
        self.streak = 0
        self.rejected = False

    def step(self, status: LicenseStatus) -> tuple[bool, bool]:
        license_valid = status == LicenseStatus.VALID
        self.streak, self.rejected = LicenseValidator._next_streak(
            self.streak, self.threshold, status
        )
        self.armed, teardown = Engine._teardown_decision(self.armed, license_valid, self.rejected)
        placement_active = self.armed  # license is not None in production
        return placement_active, teardown


def test_valid_then_transient_blips_keep_trading_until_confirmed() -> None:
    # Valid license, then a network blip, then one invalid, then recovery: the bot must
    # keep placing and never tear down across the whole transient window.
    sim = _Sim(armed_at_startup=True)
    assert sim.step(LicenseStatus.VALID) == (True, False)
    assert sim.step(LicenseStatus.ERROR) == (True, False)
    assert sim.step(LicenseStatus.INVALID) == (True, False)  # streak 1, not confirmed
    assert sim.step(LicenseStatus.ERROR) == (True, False)  # streak held at 1
    assert sim.step(LicenseStatus.VALID) == (True, False)  # recovered, streak reset


def test_valid_then_sustained_rejection_stops_and_tears_down() -> None:
    sim = _Sim(armed_at_startup=True)
    assert sim.step(LicenseStatus.VALID) == (True, False)
    assert sim.step(LicenseStatus.INVALID) == (True, False)  # 1st rejection: keep trading
    assert sim.step(LicenseStatus.INVALID) == (False, True)  # 2nd: stop + teardown


def test_invalid_from_startup_never_trades_and_never_tears_down() -> None:
    # No valid validation ever → unarmed → placement blocked throughout, and a license
    # that was never valid must not trigger teardown even once confirmed.
    sim = _Sim(armed_at_startup=False)
    assert sim.step(LicenseStatus.INVALID) == (False, False)
    assert sim.step(LicenseStatus.INVALID) == (False, False)  # confirmed, but never armed


def test_invalid_from_startup_then_valid_starts_trading() -> None:
    sim = _Sim(armed_at_startup=False)
    assert sim.step(LicenseStatus.INVALID) == (False, False)
    assert sim.step(LicenseStatus.VALID) == (True, False)  # user fixed the key → trades
