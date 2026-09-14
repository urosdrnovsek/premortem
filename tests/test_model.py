from decimal import Decimal
from pathlib import Path

import pytest

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
        people=(model.Person(name="You", notice_period_months=1),),
        flows=(
            model.Flow(name="Salary", kind=model.FlowKind.INCOME, monthly_amount=Decimal("2837.42"), owner="You"),
        ),
        assets=(model.Asset(name="ISA", value=Decimal("8123.99"), access_days=5, haircut_pct=Decimal("0.05")),),
    )
    reparsed = model.from_toml(model.to_toml(h))
    assert reparsed.flows[0].monthly_amount == Decimal("2837.42")
    assert reparsed.assets[0].value == Decimal("8123.99")
    assert reparsed.assets[0].haircut_pct == Decimal("0.05")


def test_round_trip_pins_values_to_the_documented_precision():
    # These do NOT survive float() unchanged - 0.333... has more digits than a
    # float carries - so without a precision policy the file would reload to
    # a subtly different household than the one that was saved.
    h = model.Household(
        people=(model.Person(name="You"),),
        flows=(
            model.Flow(name="Salary", kind=model.FlowKind.INCOME, monthly_amount=Decimal("1234.56789"), owner="You"),
        ),
        assets=(model.Asset(name="ISA", value=Decimal("100"), access_days=5, haircut_pct=Decimal("0.333333333333333333")),),
        income_reduction_factor=Decimal("0.666666666666666666"),
    )
    reparsed = model.from_toml(model.to_toml(h))
    assert reparsed.flows[0].monthly_amount == Decimal("1234.57")
    assert reparsed.assets[0].haircut_pct == Decimal("0.3333")
    assert reparsed.income_reduction_factor == Decimal("0.6667")
    # And the second save is a fixed point: quantized values round-trip exactly.
    assert model.from_toml(model.to_toml(reparsed)) == reparsed


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


def test_household_rejects_income_flow_without_an_owner():
    # income_flows_for() attributes income by owner, so an unowned income line
    # would be accepted and then silently never counted in any projection.
    try:
        model.Household(
            people=(model.Person(name="You"),),
            flows=(model.Flow(name="Mystery income", kind=model.FlowKind.INCOME, monthly_amount=Decimal("500")),),
            assets=(),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for income flow with no owner")


def test_household_rejects_duplicate_asset_names():
    # runway keys balances by asset name; two "Cash" entries would collapse into one.
    try:
        model.Household(
            people=(model.Person(name="You"),),
            flows=(),
            assets=(
                model.Asset(name="Cash", value=Decimal("100"), access_days=0),
                model.Asset(name="Cash", value=Decimal("200"), access_days=0),
            ),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for duplicate asset name")


def test_household_rejects_no_people():
    # primary_earner() is max() over people; an empty household would raise there,
    # outside main.py's error handling, instead of here with a message.
    try:
        model.Household(people=(), flows=(), assets=())
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a household with no people")


def test_household_rejects_income_reduction_factor_above_one():
    # A factor above 1 would turn "income drops but doesn't stop" into a raise.
    try:
        model.Household(people=(model.Person(name="You"),), flows=(), assets=(), income_reduction_factor=Decimal("1.5"))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for income_reduction_factor > 1")


def _fixture_with(old: str, new: str) -> str:
    text = FIXTURE.read_text()
    assert old in text, old
    return text.replace(old, new, 1)


@pytest.mark.parametrize(
    "old, new, expect",
    [
        # bool("false") is True - the one that would silently flip a projection.
        ('name = "Commuting"\nmonthly_amount = 180\njob_linked = true', 'name = "Commuting"\nmonthly_amount = 180\njob_linked = "true"', "job_linked"),
        ("horizon_months = 24", "horizon_months = 2.9", "horizon_months"),
        ("access_days = 5", "access_days = 5.5", "access_days"),
        ("notice_period_months = 1", 'notice_period_months = "1"', "notice_period_months"),
        ("notice_period_months = 1", "notice_period_months = true", "notice_period_months"),
        ("value = 8000", "value = inf", "value"),
        ("value = 8000", "value = nan", "value"),
        ("value = 8000", 'value = "8000"', "value"),
        ('name = "Car loan"', "name = 42", "name"),
    ],
)
def test_from_toml_rejects_wrongly_typed_fields(old, new, expect):
    with pytest.raises(ValueError, match=expect):
        model.from_toml(_fixture_with(old, new))


def test_from_toml_reports_missing_required_field():
    with pytest.raises(ValueError, match=r"assets\[2\]: missing required field 'access_days'"):
        model.from_toml(_fixture_with("access_days = 5\n", ""))


def test_from_toml_rejects_non_table_list_entry():
    # A bare array of strings at the top of the file, where TOML puts root keys.
    text = FIXTURE.read_text().split("[[debts]]")[0]
    with pytest.raises(ValueError, match=r"debts\[0\]: expected a table"):
        model.from_toml('debts = ["Car loan"]\n' + text)


@pytest.mark.parametrize("text", ["people = 3", "flows = true", 'assets = "x"'])
def test_from_toml_rejects_section_that_is_not_an_array_of_tables(text):
    # Must be a ValueError, not a TypeError from iterating an int - main.py only
    # turns the former into a friendly message.
    with pytest.raises(ValueError, match="expected an array of tables"):
        model.from_toml(text)
