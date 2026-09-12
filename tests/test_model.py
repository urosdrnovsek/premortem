from decimal import Decimal
from pathlib import Path

import model


FIXTURE = Path(__file__).parent / "fixtures" / "sample_household.toml"


def load_fixture() -> model.Household:
    return model.from_toml(FIXTURE.read_text())


def test_from_toml_parses_fixture():
    h = load_fixture()
    assert len(h.people) == 2
    assert h.person("Alex").redundancy_lump_sum == Decimal("4000")
    assert len(h.flows) == 7
    assert len(h.assets) == 4
    assert len(h.debts) == 1
    assert h.horizon_months == 24
    assert h.major_expense_amount == Decimal("3000")
    assert h.income_reduction_factor == Decimal("0.5")


def test_toml_round_trip_is_stable():
    h = load_fixture()
    reparsed = model.from_toml(model.to_toml(h))
    assert reparsed == h


def test_round_trip_preserves_decimal_values_exactly():
    h = model.Household(
        people=(model.Person(name="You", notice_period_months=Decimal("1.5")),),
        flows=(
            model.Flow(name="Salary", kind=model.FlowKind.INCOME, monthly_amount=Decimal("2837.42"), owner="You"),
        ),
        assets=(model.Asset(name="ISA", value=Decimal("8123.99"), access_days=5, haircut_pct=Decimal("0.05")),),
    )
    reparsed = model.from_toml(model.to_toml(h))
    assert reparsed.flows[0].monthly_amount == Decimal("2837.42")
    assert reparsed.assets[0].value == Decimal("8123.99")
    assert reparsed.assets[0].haircut_pct == Decimal("0.05")


def test_income_flows_for_and_primary_earner():
    h = load_fixture()
    assert sum(f.monthly_amount for f in h.income_flows_for("Alex")) == Decimal("2800")
    assert h.primary_earner().name == "Alex"


def test_job_linked_flag_round_trips():
    h = load_fixture()
    commuting = next(f for f in h.flows if f.name == "Commuting")
    groceries = next(f for f in h.flows if f.name == "Groceries")
    assert commuting.job_linked is True
    assert groceries.job_linked is False


def test_asset_rejects_haircut_pct_outside_zero_one():
    try:
        model.Asset(name="ISA", value=Decimal("100"), access_days=0, haircut_pct=Decimal("1.5"))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for haircut_pct > 1")


def test_asset_rejects_negative_access_days():
    try:
        model.Asset(name="ISA", value=Decimal("100"), access_days=-1)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for negative access_days")


def test_flow_rejects_negative_monthly_amount():
    try:
        model.Flow(name="Rent", kind=model.FlowKind.FIXED_EXPENSE, monthly_amount=Decimal("-1"))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for negative monthly_amount")


def test_household_rejects_non_positive_horizon_months():
    try:
        model.Household(
            people=(model.Person(name="You"),),
            flows=(),
            assets=(),
            horizon_months=0,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for horizon_months < 1")


def test_household_rejects_flow_owner_not_matching_a_person():
    try:
        model.Household(
            people=(model.Person(name="You"),),
            flows=(
                model.Flow(name="Salary", kind=model.FlowKind.INCOME, monthly_amount=Decimal("1000"), owner="Nobody"),
            ),
            assets=(),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for flow owner not matching any person")


def test_household_rejects_redundancy_target_asset_not_matching_an_asset():
    try:
        model.Household(
            people=(
                model.Person(
                    name="You",
                    redundancy_lump_sum=Decimal("3000"),
                    redundancy_target_asset="Nonexistent account",
                ),
            ),
            flows=(),
            assets=(),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for redundancy_target_asset not matching any asset")
