"""Single source of truth for pricing, trial, and founder cohort limits.

Every template, billing flow, and email imports from here. Do not hardcode
prices or trial-day counts anywhere else.

Env-overridable for staging / ops drills (defaults match the live site).
"""
import os


# Plan prices in INR. Year-1 is the discounted Price (40% off Year-2).
# Year-2+ is the regular Price.
FREE_PRICE_INR = 0
PRO_YEAR1_INR = int(os.getenv("PRO_YEAR1_INR", "899"))
PRO_YEAR2_INR = int(os.getenv("PRO_YEAR2_INR", "1499"))

# Annual billing ONLY — no monthly, no trial.
# (Historical monthly equivalent kept for one legacy marketing sub-site string.)
PRO_MONTHLY_INR = round(PRO_YEAR2_INR / 12)
PRO_ANNUAL_INR = PRO_YEAR2_INR

# Trial disabled (per user decision 2026-08). Keep symbol for backward compat.
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "0"))

# Founder cohort cap. First N people to join the waitlist get the badge.
# 0 or negative disables the program.
FOUNDER_COHORT_LIMIT = int(os.getenv("FOUNDER_COHORT_LIMIT", "100"))


def annual_savings_percent() -> int:
    """Year-2 annual vs Year-1 first offer. Approximate."""
    if PRO_YEAR2_INR <= 0:
        return 0
    saved = PRO_YEAR2_INR - PRO_YEAR1_INR
    return round((saved / PRO_YEAR2_INR) * 100)


def fmt_inr(amount: int) -> str:
    """Format an integer INR amount as the display string."""
    return f"₹{int(amount):,}"


def trial_label() -> str:
    """Short label used in onboarding, marketing, and email copy."""
    return "PRO · ANNUAL"
