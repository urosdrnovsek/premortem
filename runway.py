"""Household + Shock -> Projection.

Running out of cash isn't a single event: every asset has an access_days (how
long it takes to actually turn into spendable money) and a haircut_pct (what's
lost by forcing that early). Draining in order of access cost is what turns
"liquid vs illiquid" from a label into a computed result.

Insolvency is defined precisely, on purpose: the first month where income plus
assets reachable within that month, net of haircuts, cannot cover that month's
fixed obligations. Net worth is never checked.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import math

from model import Household, FlowKind
from shocks import Shock, Delta, DeltaOp, DeltaTarget


@dataclass(frozen=True)
class AssetDraw:
    asset_name: str
    gross_amount: Decimal
    haircut_applied: Decimal
    net_amount: Decimal


@dataclass(frozen=True)
class MonthSnapshot:
    month: int
    income_total: Decimal
    fixed_obligations: Decimal
    one_off_need: Decimal
    variable_spend_planned: Decimal
    variable_spend_paid: Decimal
    draws: tuple[AssetDraw, ...]
    solvent: bool


@dataclass(frozen=True)
class Projection:
    shock: Shock
    months: tuple[MonthSnapshot, ...]
    insolvent_month: int | None


def _reachable_month(access_days: int) -> int:
    return math.ceil(access_days / 30)


def _fastest_asset_name(household: Household) -> str | None:
    if not household.assets:
        return None
    return min(household.assets, key=lambda a: (a.access_days, a.haircut_pct)).name


def _draw_waterfall(
    need: Decimal,
    balances: dict[str, Decimal],
    haircuts: dict[str, Decimal],
    access_days: dict[str, int],
    current_month: int,
) -> tuple[Decimal, list[AssetDraw], Decimal]:
    """Draw `need` (net, post-haircut) from reachable assets, cheapest access first.
    Returns (net_covered, draws, remaining_shortfall). Mutates `balances` in place.
    """
    if need <= 0:
        return Decimal("0"), [], Decimal("0")

    reachable = sorted(
        (name for name, bal in balances.items()
         if bal > 0 and _reachable_month(access_days[name]) <= current_month),
        key=lambda name: (access_days[name], haircuts[name]),
    )

    remaining = need
    draws: list[AssetDraw] = []
    for name in reachable:
        if remaining <= 0:
            break
        haircut = haircuts[name]
        balance = balances[name]
        available_net = balance * (Decimal("1") - haircut)
        if available_net <= remaining:
            gross = balance
            net = available_net
            balances[name] = Decimal("0")
        else:
            gross = remaining / (Decimal("1") - haircut) if haircut < 1 else balance
            net = remaining
            balances[name] = balance - gross
        if gross > 0:
            draws.append(AssetDraw(asset_name=name, gross_amount=gross, haircut_applied=haircut, net_amount=net))
            remaining -= net

    covered = need - remaining
    return covered, draws, max(remaining, Decimal("0"))


def project(household: Household, shock: Shock) -> Projection:
    balances: dict[str, Decimal] = {a.name: a.value for a in household.assets}
    haircuts: dict[str, Decimal] = {a.name: a.haircut_pct for a in household.assets}
    access_days: dict[str, int] = {a.name: a.access_days for a in household.assets}

    income_override: dict[str, Decimal] = {}
    benefits_floor_active: dict[str, Decimal] = {}
    job_linked_variable_active = True

    fixed_flows_total = sum(
        (f.monthly_amount for f in household.flows if f.kind == FlowKind.FIXED_EXPENSE), Decimal("0")
    )
    debt_balances: dict[str, Decimal] = {d.name: d.balance for d in household.debts}

    baseline_income_total = sum(
        (f.monthly_amount for p in household.people for f in household.income_flows_for(p.name)),
        Decimal("0"),
    )

    variable_flows = [f for f in household.flows if f.kind == FlowKind.VARIABLE_EXPENSE]

    deltas_by_month: dict[int, list[Delta]] = {}
    for d in shock.deltas:
        deltas_by_month.setdefault(d.month, []).append(d)

    months: list[MonthSnapshot] = []
    insolvent_month: int | None = None

    for month in range(household.horizon_months):
        one_off_need = Decimal("0")
        for d in deltas_by_month.get(month, []):
            if d.target == DeltaTarget.PERSON_INCOME and d.op == DeltaOp.SET:
                income_override[d.ref] = d.value
            elif d.target == DeltaTarget.JOB_LINKED_VARIABLE and d.op == DeltaOp.SET:
                job_linked_variable_active = False
            elif d.target == DeltaTarget.BENEFITS_FLOOR and d.op == DeltaOp.SET:
                benefits_floor_active[d.ref] = d.value
            elif d.target == DeltaTarget.ASSET and d.op == DeltaOp.ADD:
                if d.value >= 0:
                    target = d.ref or _fastest_asset_name(household) or "Unassigned lump sum"
                    if target not in balances:
                        # No real asset by this name (e.g. a redundancy payout with no
                        # target asset, or none configured at all) - land it somewhere
                        # spendable immediately rather than losing track of it or
                        # crashing the waterfall below on a name it doesn't know.
                        balances[target] = Decimal("0")
                        haircuts[target] = Decimal("0")
                        access_days[target] = 0
                    balances[target] += d.value
                else:
                    one_off_need += -d.value

        income_total = Decimal("0")
        for person in household.people:
            baseline = sum(
                (f.monthly_amount for f in household.income_flows_for(person.name)), Decimal("0")
            )
            income_total += income_override.get(person.name, baseline)
            income_total += benefits_floor_active.get(person.name, Decimal("0"))

        variable_spend_planned = sum(
            (f.monthly_amount for f in variable_flows
             if job_linked_variable_active or not f.job_linked),
            Decimal("0"),
        )

        # Income below what it'd be with nothing wrong - not "some delta fired at
        # some point" - so a recovery (new job, benefits ending) lifts the cut on
        # its own, and a one-off ASSET event (major_expense) never trips it at all.
        shock_active = income_total < baseline_income_total

        debt_due = sum(
            (min(debt_balances[d.name], d.minimum_monthly_payment)
             for d in household.debts if debt_balances[d.name] > 0),
            Decimal("0"),
        )
        fixed_total = fixed_flows_total + debt_due

        required = fixed_total + one_off_need
        shortfall_required = max(Decimal("0"), required - income_total)
        _, draws, remaining = _draw_waterfall(
            shortfall_required, balances, haircuts, access_days, month
        )
        solvent = remaining <= 0

        variable_spend_paid = Decimal("0")
        if solvent:
            leftover_income = max(Decimal("0"), income_total - required)
            if shock_active:
                # A household actually under a shock cuts discretionary spending
                # before it starts selling assets to fund takeaways and streaming.
                variable_spend_paid = min(variable_spend_planned, leftover_income)
            else:
                variable_need = max(Decimal("0"), variable_spend_planned - leftover_income)
                var_covered, var_draws, var_remaining = _draw_waterfall(
                    variable_need, balances, haircuts, access_days, month
                )
                variable_spend_paid = min(variable_spend_planned, leftover_income + var_covered)
                draws = draws + var_draws

        if solvent:
            # Decoupled from the variable-spend branch above on purpose: this is a
            # separate decision (only decrement what was actually paid this month)
            # rather than an accident of both being nested under the same check.
            for d in household.debts:
                if debt_balances[d.name] > 0:
                    debt_balances[d.name] -= min(debt_balances[d.name], d.minimum_monthly_payment)

        months.append(
            MonthSnapshot(
                month=month,
                income_total=income_total,
                fixed_obligations=fixed_total,
                one_off_need=one_off_need,
                variable_spend_planned=variable_spend_planned,
                variable_spend_paid=variable_spend_paid,
                draws=tuple(draws),
                solvent=solvent,
            )
        )

        if not solvent:
            insolvent_month = month
            break

    return Projection(shock=shock, months=tuple(months), insolvent_month=insolvent_month)
