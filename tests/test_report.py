from decimal import Decimal
from pathlib import Path

import model
import shocks
import runway
from report.render import render_html, build_context

FIXTURE = Path(__file__).parent / "fixtures" / "sample_household.toml"


def _load_projections():
    household = model.from_toml(FIXTURE.read_text())
    projections = [runway.project(household, s) for s in shocks.presets(household)]
    return household, projections


def test_build_context_has_one_row_per_shock():
    household, projections = _load_projections()
    ctx = build_context(household, projections)
    assert len(ctx["shocks"]) == len(projections) == 5
    assert ctx["currency"] == "£"


def test_render_html_is_well_formed_and_mentions_insolvency_definition():
    household, projections = _load_projections()
    html = render_html(household, projections)
    assert "<html>" in html and "</html>" in html
    assert "Insolvent means" in html
    for p in projections:
        assert p.shock.label in html


def test_render_html_shows_a_waterfall_narrative_when_a_slow_asset_is_drawn():
    # Deliberately cash-poor: month 0's shortfall is covered entirely by instant
    # cash, but the recurring shortfall in month 1 can only be met once the
    # 5-day-access ISA becomes reachable - that's the draw the narrative should surface.
    household = model.Household(
        people=(model.Person(name="You", notice_period_months=Decimal("0")),),
        flows=(
            model.Flow(name="Salary", kind=model.FlowKind.INCOME, monthly_amount=Decimal("2000"), owner="You"),
            model.Flow(name="Rent", kind=model.FlowKind.FIXED_EXPENSE, monthly_amount=Decimal("1000")),
        ),
        assets=(
            model.Asset(name="Current account", value=Decimal("1000"), access_days=0),
            model.Asset(name="Stocks ISA", value=Decimal("5000"), access_days=5, haircut_pct=Decimal("0.1")),
        ),
        currency_label="£",
        horizon_months=3,
    )
    shock = shocks.job_loss(household.person("You"))
    projection = runway.project(household, shock)
    assert projection.insolvent_month is None

    html = render_html(household, [projection])
    assert "Worth noticing" in html
    assert "Stocks ISA" in html
    assert "5 day" in html
    assert "10% haircut" in html


def test_months_label_does_not_claim_safety_beyond_the_horizon():
    # Exactly enough to survive every month of a 3-month horizon and not a penny
    # more: month 3 would fail immediately, so "safe beyond" would be a lie.
    household = model.Household(
        people=(model.Person(name="You"),),
        flows=(model.Flow(name="Rent", kind=model.FlowKind.FIXED_EXPENSE, monthly_amount=Decimal("1000")),),
        assets=(model.Asset(name="Cash", value=Decimal("3000"), access_days=0),),
        currency_label="£",
        horizon_months=3,
        major_expense_amount=Decimal("0"),
    )
    projection = runway.project(household, shocks.income_reduction(household.person("You"), household))
    assert projection.insolvent_month is None
    assert projection.months[-1].draws[-1].net_amount == Decimal("1000")

    ctx = build_context(household, [projection])
    label = ctx["shocks"][0]["months_label"]
    assert label == "3+ months"
    assert "beyond" not in label.lower()


def test_fixed_obligations_total_caps_each_debt_at_its_balance():
    household = model.Household(
        people=(model.Person(name="You"),),
        flows=(model.Flow(name="Rent", kind=model.FlowKind.FIXED_EXPENSE, monthly_amount=Decimal("1000")),),
        assets=(model.Asset(name="Cash", value=Decimal("100"), access_days=0),),
        debts=(
            model.Debt(name="Nearly paid off", balance=Decimal("25"), minimum_monthly_payment=Decimal("100")),
            model.Debt(name="Paid off", balance=Decimal("0"), minimum_monthly_payment=Decimal("50")),
        ),
        currency_label="£",
        horizon_months=1,
    )
    projection = runway.project(household, shocks.major_expense(household))
    ctx = build_context(household, [projection])
    # What the simulator actually charges in month 0, not the sum of configured minimums (1150).
    assert projection.months[0].fixed_obligations == Decimal("1025")
    assert ctx["total_fixed"] == "£1,025"
