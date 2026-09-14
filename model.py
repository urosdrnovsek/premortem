"""Household, Person, Flow, Asset, Debt — the data this whole project is about.

Also owns TOML (de)serialization: this is the one file both `elicit/` (writes a
Household out) and `report/`/`main.py` (read one back in) depend on, so the file
format lives next to the shape it describes.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal
from enum import Enum
import tomllib
import tomli_w


class FlowKind(str, Enum):
    INCOME = "income"
    FIXED_EXPENSE = "fixed_expense"
    VARIABLE_EXPENSE = "variable_expense"


@dataclass(frozen=True)
class Flow:
    name: str
    kind: FlowKind
    monthly_amount: Decimal
    owner: str | None = None
    job_linked: bool = False

    def __post_init__(self) -> None:
        if self.monthly_amount < 0:
            raise ValueError(f"flow {self.name!r}: monthly_amount must be >= 0, got {self.monthly_amount}")


@dataclass(frozen=True)
class Person:
    name: str
    notice_period_months: int = 0
    redundancy_lump_sum: Decimal = Decimal("0")
    redundancy_target_asset: str | None = None
    benefits_floor_monthly: Decimal = Decimal("0")
    benefits_delay_months: int = 0

    def __post_init__(self) -> None:
        for field_name in ("notice_period_months", "redundancy_lump_sum", "benefits_floor_monthly", "benefits_delay_months"):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(f"person {self.name!r}: {field_name} must be >= 0, got {value}")


@dataclass(frozen=True)
class Asset:
    name: str
    value: Decimal
    access_days: int
    haircut_pct: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.value < 0:
            raise ValueError(f"asset {self.name!r}: value must be >= 0, got {self.value}")
        if self.access_days < 0:
            raise ValueError(f"asset {self.name!r}: access_days must be >= 0, got {self.access_days}")
        if not (0 <= self.haircut_pct <= 1):
            raise ValueError(f"asset {self.name!r}: haircut_pct must be between 0 and 1, got {self.haircut_pct}")


@dataclass(frozen=True)
class Debt:
    name: str
    balance: Decimal
    minimum_monthly_payment: Decimal

    def __post_init__(self) -> None:
        if self.balance < 0:
            raise ValueError(f"debt {self.name!r}: balance must be >= 0, got {self.balance}")
        if self.minimum_monthly_payment < 0:
            raise ValueError(f"debt {self.name!r}: minimum_monthly_payment must be >= 0, got {self.minimum_monthly_payment}")


@dataclass(frozen=True)
class Household:
    people: tuple[Person, ...]
    flows: tuple[Flow, ...]
    assets: tuple[Asset, ...]
    debts: tuple[Debt, ...] = ()
    currency_label: str = ""
    horizon_months: int = 24
    major_expense_amount: Decimal = Decimal("3000")
    major_expense_label: str = "Boiler / major home repair"
    income_reduction_factor: Decimal = Decimal("0.5")

    def __post_init__(self) -> None:
        if self.horizon_months < 1:
            raise ValueError(f"horizon_months must be >= 1, got {self.horizon_months}")
        if self.major_expense_amount < 0:
            raise ValueError(f"major_expense_amount must be >= 0, got {self.major_expense_amount}")
        if not (0 <= self.income_reduction_factor <= 1):
            raise ValueError(f"income_reduction_factor must be between 0 and 1, got {self.income_reduction_factor}")
        if not self.people:
            raise ValueError("household must have at least one person")

        # runway keys assets and debts by name, so a duplicate would silently
        # collapse two balances into one.
        for label, items in (("person", self.people), ("asset", self.assets), ("debt", self.debts)):
            seen: set[str] = set()
            for item in items:
                if item.name in seen:
                    raise ValueError(f"duplicate {label} name {item.name!r}")
                seen.add(item.name)

        person_names = {p.name for p in self.people}
        for f in self.flows:
            if f.kind == FlowKind.INCOME and not f.owner:
                raise ValueError(f"flow {f.name!r}: income must have an owner")
            if f.owner and f.owner not in person_names:
                raise ValueError(f"flow {f.name!r}: owner {f.owner!r} does not match any person")

        asset_names = {a.name for a in self.assets}
        for p in self.people:
            if p.redundancy_target_asset and p.redundancy_target_asset not in asset_names:
                raise ValueError(
                    f"person {p.name!r}: redundancy_target_asset {p.redundancy_target_asset!r} does not match any asset"
                )

    def person(self, name: str) -> Person:
        for p in self.people:
            if p.name == name:
                return p
        raise KeyError(f"no person named {name!r}")

    def income_flows_for(self, name: str) -> tuple[Flow, ...]:
        return tuple(f for f in self.flows if f.kind == FlowKind.INCOME and f.owner == name)

    def primary_earner(self) -> Person:
        """The person with the largest total monthly income."""
        def total_income(p: Person) -> Decimal:
            return sum((f.monthly_amount for f in self.income_flows_for(p.name)), Decimal("0"))
        return max(self.people, key=total_income)


# tomllib already gives us typed values, so a strict reader's only job is to refuse
# the wrong type loudly instead of coercing it - `bool("false")` is True, `int(2.9)`
# is 2, `Decimal("inf")` compares happily right up until it doesn't - and each of
# those would quietly change a projection of a hand-edited file.
_MISSING = object()


def _get(table: object, where: str, key: str, kind: type, default: object = _MISSING) -> object:
    if not isinstance(table, dict):
        raise ValueError(f"{where}: expected a table, got {table!r}")
    if key in table:
        value = table[key]
    elif default is _MISSING:
        raise ValueError(f"{where}: missing required field {key!r}")
    else:
        value = default  # checked and converted like a real value, so a Decimal field's 0 comes back as Decimal
    # bool is an int subclass; a TOML `true` must never pass as a number.
    if kind is Decimal:
        ok = isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    else:
        ok = isinstance(value, kind) and (kind is bool or not isinstance(value, bool))
    if not ok:
        wanted = {str: "a string", int: "a whole number", bool: "true or false", Decimal: "a number"}[kind]
        raise ValueError(f"{where}: {key} must be {wanted}, got {value!r}")
    if kind is Decimal:
        # Decimal(str(float)) uses Python's shortest round-trip repr - the same
        # repr tomli_w writes - so a saved file reloads to the value it was saved from.
        value = Decimal(str(value))
        if not value.is_finite():
            raise ValueError(f"{where}: {key} must be a finite number, got {value!r}")
    return value


# Precision policy for the saved file. TOML has no Decimal type, so amounts are
# written as floats; a float only reproduces a decimal exactly up to ~15
# significant digits, so values are pinned to a fixed scale first - money to the
# cent, ratios (haircuts, the income-reduction factor) to four places - which
# keeps every realistic household inside the range that round-trips exactly.
MONEY_PLACES = Decimal("0.01")
RATIO_PLACES = Decimal("0.0001")


def _money(value: Decimal) -> float:
    return float(value.quantize(MONEY_PLACES))


def _ratio(value: Decimal) -> float:
    return float(value.quantize(RATIO_PLACES))


def to_toml(household: Household) -> str:
    doc: dict = {
        "meta": {
            "currency_label": household.currency_label,
            "horizon_months": household.horizon_months,
        },
        "assumptions": {
            "major_expense_amount": _money(household.major_expense_amount),
            "major_expense_label": household.major_expense_label,
            "income_reduction_factor": _ratio(household.income_reduction_factor),
        },
        "people": [
            {
                "name": p.name,
                "notice_period_months": p.notice_period_months,
                "redundancy_lump_sum": _money(p.redundancy_lump_sum),
                "redundancy_target_asset": p.redundancy_target_asset or "",
                "benefits_floor_monthly": _money(p.benefits_floor_monthly),
                "benefits_delay_months": p.benefits_delay_months,
            }
            for p in household.people
        ],
        "flows": [
            {
                "kind": f.kind.value,
                "name": f.name,
                "monthly_amount": _money(f.monthly_amount),
                "owner": f.owner or "",
                "job_linked": f.job_linked,
            }
            for f in household.flows
        ],
        "assets": [
            {
                "name": a.name,
                "value": _money(a.value),
                "access_days": a.access_days,
                "haircut_pct": _ratio(a.haircut_pct),
            }
            for a in household.assets
        ],
        "debts": [
            {
                "name": d.name,
                "balance": _money(d.balance),
                "minimum_monthly_payment": _money(d.minimum_monthly_payment),
            }
            for d in household.debts
        ],
    }
    return tomli_w.dumps(doc)


def _section(doc: dict, name: str) -> list:
    entries = doc.get(name, [])
    if not isinstance(entries, list):
        raise ValueError(f"{name}: expected an array of tables ([[{name}]]), got {entries!r}")
    return entries


def from_toml(text: str) -> Household:
    doc = tomllib.loads(text)
    meta = doc.get("meta", {})
    assumptions = doc.get("assumptions", {})

    people = tuple(
        Person(
            name=_get(p, f"people[{i}]", "name", str),
            notice_period_months=_get(p, f"people[{i}]", "notice_period_months", int, 0),
            redundancy_lump_sum=_get(p, f"people[{i}]", "redundancy_lump_sum", Decimal, 0),
            redundancy_target_asset=_get(p, f"people[{i}]", "redundancy_target_asset", str, "") or None,
            benefits_floor_monthly=_get(p, f"people[{i}]", "benefits_floor_monthly", Decimal, 0),
            benefits_delay_months=_get(p, f"people[{i}]", "benefits_delay_months", int, 0),
        )
        for i, p in enumerate(_section(doc, "people"))
    )
    flows = tuple(
        Flow(
            name=_get(f, f"flows[{i}]", "name", str),
            kind=FlowKind(_get(f, f"flows[{i}]", "kind", str)),
            monthly_amount=_get(f, f"flows[{i}]", "monthly_amount", Decimal),
            owner=_get(f, f"flows[{i}]", "owner", str, "") or None,
            job_linked=_get(f, f"flows[{i}]", "job_linked", bool, False),
        )
        for i, f in enumerate(_section(doc, "flows"))
    )
    assets = tuple(
        Asset(
            name=_get(a, f"assets[{i}]", "name", str),
            value=_get(a, f"assets[{i}]", "value", Decimal),
            access_days=_get(a, f"assets[{i}]", "access_days", int),
            haircut_pct=_get(a, f"assets[{i}]", "haircut_pct", Decimal, 0),
        )
        for i, a in enumerate(_section(doc, "assets"))
    )
    debts = tuple(
        Debt(
            name=_get(d, f"debts[{i}]", "name", str),
            balance=_get(d, f"debts[{i}]", "balance", Decimal),
            minimum_monthly_payment=_get(d, f"debts[{i}]", "minimum_monthly_payment", Decimal),
        )
        for i, d in enumerate(_section(doc, "debts"))
    )

    return Household(
        people=people,
        flows=flows,
        assets=assets,
        debts=debts,
        currency_label=_get(meta, "meta", "currency_label", str, ""),
        horizon_months=_get(meta, "meta", "horizon_months", int, 24),
        major_expense_amount=_get(assumptions, "assumptions", "major_expense_amount", Decimal, 3000),
        major_expense_label=_get(assumptions, "assumptions", "major_expense_label", str, "Boiler / major home repair"),
        income_reduction_factor=_get(assumptions, "assumptions", "income_reduction_factor", Decimal, Decimal("0.5")),
    )
