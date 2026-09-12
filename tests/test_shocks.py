from decimal import Decimal
from pathlib import Path

import model
import shocks


FIXTURE = Path(__file__).parent / "fixtures" / "sample_household.toml"


def load_fixture() -> model.Household:
    return model.from_toml(FIXTURE.read_text())


def test_presets_count_matches_household_size():
    h = load_fixture()
    assert len(h.people) == 2
    assert len(shocks.presets(h)) == 5

    single = model.Household(
        people=(model.Person(name="Solo"),),
        flows=(model.Flow(name="Salary", kind=model.FlowKind.INCOME, monthly_amount=Decimal("3000"), owner="Solo"),),
        assets=(model.Asset(name="Cash", value=Decimal("1000"), access_days=0),),
    )
    assert len(shocks.presets(single)) == 4


def test_job_loss_timeline_shape():
    h = load_fixture()
    alex = h.person("Alex")
    shock = shocks.job_loss(alex)
    by_target = {(d.month, d.target): d for d in shock.deltas}

    # notice period = 1 month -> income stops at month 1, not month 0
    income_delta = by_target[(1, shocks.DeltaTarget.PERSON_INCOME)]
    assert income_delta.value == Decimal("0")

    redundancy_delta = by_target[(1, shocks.DeltaTarget.ASSET)]
    assert redundancy_delta.value == Decimal("4000")
    assert redundancy_delta.ref == "Current account"

    assert (1, shocks.DeltaTarget.JOB_LINKED_VARIABLE) in by_target

    # benefits_delay_months = 2, measured from job end (month 1) -> month 3
    benefits_delta = by_target[(3, shocks.DeltaTarget.BENEFITS_FLOOR)]
    assert benefits_delta.value == Decimal("800")


def test_major_expense_is_a_negative_unref_asset_delta():
    h = load_fixture()
    shock = shocks.major_expense(h)
    assert len(shock.deltas) == 1
    d = shock.deltas[0]
    assert d.month == 0
    assert d.target == shocks.DeltaTarget.ASSET
    assert d.ref is None
    assert d.value == Decimal("-3000")


def test_income_reduction_uses_absolute_amount_not_raw_factor():
    h = load_fixture()
    alex = h.person("Alex")
    shock = shocks.income_reduction(alex, h)
    d = shock.deltas[0]
    # Alex earns 2800/month baseline; factor 0.5 -> reduced income is 1400, not 0.5
    assert d.value == Decimal("1400.0")


def test_compound_merges_and_sorts_by_month():
    h = load_fixture()
    alex = h.person("Alex")
    combined = shocks.compound(
        shocks.job_loss(alex), shocks.major_expense(h),
        key="k", label="l", description="d",
    )
    months = [d.month for d in combined.deltas]
    assert months == sorted(months)
    assert any(d.target == shocks.DeltaTarget.ASSET and d.value == Decimal("-3000") for d in combined.deltas)
    assert any(d.target == shocks.DeltaTarget.PERSON_INCOME for d in combined.deltas)
