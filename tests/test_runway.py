from decimal import Decimal

import pytest

import model
import runway
import shocks


def make_household(**overrides) -> model.Household:
    defaults = dict(
        people=(model.Person(name="You", notice_period_months=Decimal("0")),),
        flows=(
            model.Flow(name="Salary", kind=model.FlowKind.INCOME, monthly_amount=Decimal("2000"), owner="You"),
            model.Flow(name="Rent", kind=model.FlowKind.FIXED_EXPENSE, monthly_amount=Decimal("1000")),
            model.Flow(name="Groceries", kind=model.FlowKind.VARIABLE_EXPENSE, monthly_amount=Decimal("300")),
        ),
        assets=(model.Asset(name="Cash", value=Decimal("500"), access_days=0),),
        debts=(),
        horizon_months=6,
    )
    defaults.update(overrides)
    return model.Household(**defaults)


def no_op_shock() -> shocks.Shock:
    return shocks.Shock(key="none", label="none", description="", deltas=())


def test_no_shock_stays_solvent_when_income_covers_fixed_costs():
    h = make_household()
    proj = runway.project(h, no_op_shock())
    assert proj.insolvent_month is None
    assert all(m.solvent for m in proj.months)
    assert len(proj.months) == h.horizon_months


def test_job_loss_with_no_savings_goes_insolvent_immediately_after_notice():
    h = make_household(
        people=(model.Person(name="You", notice_period_months=Decimal("0")),),
        assets=(model.Asset(name="Cash", value=Decimal("0"), access_days=0),),
    )
    shock = shocks.job_loss(h.person("You"))
    proj = runway.project(h, shock)
    # income stops at month 0 (no notice), no redundancy, no cash -> insolvent month 0
    assert proj.insolvent_month == 0


def test_waterfall_drains_cheapest_access_asset_first():
    h = make_household(
        people=(model.Person(name="You", notice_period_months=Decimal("0")),),
        assets=(
            model.Asset(name="Slow ISA", value=Decimal("10000"), access_days=5, haircut_pct=Decimal("0.1")),
            model.Asset(name="Cash", value=Decimal("2000"), access_days=0, haircut_pct=Decimal("0")),
        ),
    )
    shock = shocks.job_loss(h.person("You"))
    proj = runway.project(h, shock)
    month0 = proj.months[0]
    assert month0.solvent
    drawn_names = [d.asset_name for d in month0.draws]
    assert drawn_names[0] == "Cash"


def test_haircut_reduces_net_proceeds_from_forced_liquidation():
    h = make_household(
        people=(model.Person(name="You", notice_period_months=Decimal("0")),),
        assets=(model.Asset(name="ISA", value=Decimal("2000"), access_days=0, haircut_pct=Decimal("0.5")),),
    )
    shock = shocks.job_loss(h.person("You"))
    proj = runway.project(h, shock)
    month0 = proj.months[0]
    draw = month0.draws[0]
    # need 1000 net (fixed obligations) with a 50% haircut -> must draw 2000 gross
    assert draw.gross_amount == Decimal("2000")
    assert draw.net_amount == Decimal("1000")


def test_illiquid_asset_with_huge_access_days_never_reached_within_horizon():
    h = make_household(
        people=(model.Person(name="You", notice_period_months=Decimal("0")),),
        assets=(model.Asset(name="Pension", value=Decimal("100000"), access_days=36500),),
        horizon_months=6,
    )
    shock = shocks.job_loss(h.person("You"))
    proj = runway.project(h, shock)
    assert proj.insolvent_month == 0
    assert proj.months[0].draws == ()


def test_insolvency_is_about_fixed_obligations_not_net_worth():
    # Large debt balance (huge negative net worth) but minimum payment is small
    # and comfortably covered by income -> not insolvent, despite negative net worth.
    h = make_household(
        debts=(model.Debt(name="Big loan", balance=Decimal("500000"), minimum_monthly_payment=Decimal("50")),),
    )
    proj = runway.project(h, no_op_shock())
    assert proj.insolvent_month is None


def test_benefits_floor_arrives_after_delay_and_restores_solvency():
    h = make_household(
        people=(model.Person(
            name="You", notice_period_months=Decimal("0"),
            benefits_floor_monthly=Decimal("1000"), benefits_delay_months=Decimal("2"),
        ),),
        assets=(model.Asset(name="Cash", value=Decimal("2500"), access_days=0),),
        horizon_months=6,
    )
    shock = shocks.job_loss(h.person("You"))
    proj = runway.project(h, shock)
    # months 0-1: no income, drawing down 1000/month fixed obligations from 2500 cash
    # month 2: benefits floor (1000) arrives but fixed obligations are 1000 -> exactly covered
    assert proj.insolvent_month is None
    month2 = proj.months[2]
    assert month2.income_total == Decimal("1000")
    assert month2.solvent


def test_variable_spend_is_cut_before_insolvency_is_triggered():
    # Enough to cover fixed obligations but not variable spend -> not insolvent,
    # variable_spend_paid should be reduced rather than triggering insolvency.
    h = make_household(
        people=(model.Person(name="You", notice_period_months=Decimal("0")),),
        assets=(model.Asset(name="Cash", value=Decimal("1000"), access_days=0),),
        horizon_months=1,
    )
    shock = shocks.job_loss(h.person("You"))
    proj = runway.project(h, shock)
    month0 = proj.months[0]
    assert month0.solvent
    assert month0.variable_spend_paid < month0.variable_spend_planned
    assert month0.variable_spend_paid == Decimal("0")


def test_redundancy_lump_sum_with_no_assets_does_not_crash():
    # Zero-asset household: the redundancy payout has nowhere real to land, but
    # project() must still complete instead of KeyError-ing in the waterfall.
    h = make_household(
        people=(model.Person(
            name="You", notice_period_months=Decimal("0"),
            redundancy_lump_sum=Decimal("3000"), redundancy_target_asset=None,
        ),),
        assets=(),
    )
    shock = shocks.job_loss(h.person("You"))
    proj = runway.project(h, shock)
    # the 3000 lump sum lands in an implicit account and covers the 1000 fixed cost
    assert proj.months[0].solvent


def test_redundancy_target_asset_unknown_name_rejected_at_construction():
    # A redundancy_target_asset that doesn't match any real asset (e.g. a stale
    # or hand-typed name in the TOML) is now caught by Household.__post_init__
    # instead of reaching the waterfall at all.
    with pytest.raises(ValueError):
        make_household(
            people=(model.Person(
                name="You", notice_period_months=Decimal("0"),
                redundancy_lump_sum=Decimal("3000"), redundancy_target_asset="Nonexistent account",
            ),),
            assets=(),
        )


def test_major_expense_competes_with_fixed_obligations_same_month():
    h = make_household(
        people=(model.Person(name="You", notice_period_months=Decimal("0")),),
        assets=(model.Asset(name="Cash", value=Decimal("1200"), access_days=0),),
        major_expense_amount=Decimal("1000"),
    )
    shock = shocks.major_expense(h)
    proj = runway.project(h, shock)
    # income 2000 exactly covers fixed 1000 + the 1000 boiler bill; variable
    # spend then draws from the 1200 cash pool instead - solvent either way.
    assert proj.months[0].solvent
    assert proj.months[0].one_off_need == Decimal("1000")
