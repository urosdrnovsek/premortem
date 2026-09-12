"""A Shock is a timeline of dated Deltas, not a modified Household.

Modelling job loss as "income = 0" from month zero is meaningfully wrong in the
optimistic direction: it skips the notice period, the redundancy lump sum, and
the fact that some spending (commute, childcare) only disappears once the job
actually ends. Encoding shocks as data — a list of (month, target, op, value)
deltas — keeps that timeline explicit and inspectable instead of buried in code.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from model import Household, Person


class DeltaOp(str, Enum):
    SET = "set"
    ADD = "add"


class DeltaTarget(str, Enum):
    PERSON_INCOME = "person_income"
    JOB_LINKED_VARIABLE = "job_linked_variable"
    ASSET = "asset"
    BENEFITS_FLOOR = "benefits_floor"


@dataclass(frozen=True)
class Delta:
    month: int
    target: DeltaTarget
    op: DeltaOp
    value: Decimal
    ref: str | None = None


@dataclass(frozen=True)
class Shock:
    key: str
    label: str
    description: str
    deltas: tuple[Delta, ...]


def job_loss(person: Person) -> Shock:
    notice_months = int(person.notice_period_months)
    benefits_start = notice_months + int(person.benefits_delay_months)

    deltas: list[Delta] = []

    # Income continues at full pay through the notice period, then stops.
    deltas.append(
        Delta(month=notice_months, target=DeltaTarget.PERSON_INCOME, op=DeltaOp.SET,
              value=Decimal("0"), ref=person.name)
    )
    # The redundancy lump sum lands the month the job actually ends.
    if person.redundancy_lump_sum > 0:
        deltas.append(
            Delta(month=notice_months, target=DeltaTarget.ASSET, op=DeltaOp.ADD,
                  value=person.redundancy_lump_sum, ref=person.redundancy_target_asset)
        )
    # Job-linked variable spend (commute, childcare, ...) drops out once the job ends.
    deltas.append(
        Delta(month=notice_months, target=DeltaTarget.JOB_LINKED_VARIABLE, op=DeltaOp.SET,
              value=Decimal("0"), ref=None)
    )
    # Benefits floor kicks in after its own delay, measured from job end.
    if person.benefits_floor_monthly > 0:
        deltas.append(
            Delta(month=benefits_start, target=DeltaTarget.BENEFITS_FLOOR, op=DeltaOp.SET,
                  value=person.benefits_floor_monthly, ref=person.name)
        )

    return Shock(
        key=f"job_loss_{person.name.lower().replace(' ', '_')}",
        label=f"{person.name} loses their job",
        description=(
            f"{person.name}'s income continues for {notice_months} month(s) of notice, then a "
            f"redundancy payment arrives and income stops. Job-linked spending drops with it"
            + (f"; a benefits floor begins {int(person.benefits_delay_months)} month(s) later." if person.benefits_floor_monthly > 0 else ".")
        ),
        deltas=tuple(sorted(deltas, key=lambda d: d.month)),
    )


def major_expense(household: Household) -> Shock:
    deltas = (
        Delta(month=0, target=DeltaTarget.ASSET, op=DeltaOp.ADD,
              value=-household.major_expense_amount, ref=None),
    )
    return Shock(
        key="major_expense",
        label=household.major_expense_label,
        description=(
            f"An unplanned {household.major_expense_label.lower()} costing "
            f"{household.currency_label}{household.major_expense_amount:,.0f} hits immediately, "
            f"drawn from whichever assets are cheapest and fastest to reach."
        ),
        deltas=deltas,
    )


def income_reduction(person: Person, household: Household) -> Shock:
    baseline = sum((f.monthly_amount for f in household.income_flows_for(person.name)), Decimal("0"))
    reduced_income = baseline * household.income_reduction_factor
    deltas = (
        Delta(month=0, target=DeltaTarget.PERSON_INCOME, op=DeltaOp.SET,
              value=reduced_income, ref=person.name),
    )
    return Shock(
        key=f"income_reduction_{person.name.lower().replace(' ', '_')}",
        label=f"{person.name}'s income drops but doesn't stop",
        description=(
            f"{person.name}'s income steps down to "
            f"{household.income_reduction_factor * 100:.0f}% of its current level indefinitely "
            f"(reduced hours, lost commission) — no redundancy, no benefits floor."
        ),
        deltas=deltas,
    )


def compound(*parts: Shock, key: str, label: str, description: str) -> Shock:
    merged = sorted((d for s in parts for d in s.deltas), key=lambda d: d.month)
    return Shock(key=key, label=label, description=description, deltas=tuple(merged))


def presets(household: Household) -> list[Shock]:
    """One job_loss per person, plus major_expense, income_reduction (applied to the
    primary earner), and a compound of the primary earner's job loss with the major
    expense — the "cold winter" scenario. A single-adult household gets 4 shocks; a
    two-adult household gets 5.
    """
    primary = household.primary_earner()

    shocks = [job_loss(p) for p in household.people]
    shocks.append(major_expense(household))
    shocks.append(income_reduction(primary, household))
    shocks.append(
        compound(
            job_loss(primary),
            major_expense(household),
            key="compound_job_loss_and_expense",
            label=f"{primary.name} loses their job and {household.major_expense_label.lower()} hits",
            description=(
                f"{primary.name}'s job loss and an unplanned {household.major_expense_label.lower()} "
                "land in the same window — the two aren't independent in a cold winter."
            ),
        )
    )
    return shocks
