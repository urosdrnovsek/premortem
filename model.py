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


def _dec(value: object) -> Decimal:
    """TOML has no Decimal type — floats/ints round-trip through Decimal(str(...))
    because tomli_w writes floats using Python's shortest-round-trip repr."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _num(value: Decimal) -> float:
    return float(value)


def to_toml(household: Household) -> str:
    doc: dict = {
        "meta": {
            "currency_label": household.currency_label,
            "horizon_months": household.horizon_months,
        },
        "assumptions": {
            "major_expense_amount": _num(household.major_expense_amount),
            "major_expense_label": household.major_expense_label,
            "income_reduction_factor": _num(household.income_reduction_factor),
        },
        "people": [
            {
                "name": p.name,
                "notice_period_months": p.notice_period_months,
                "redundancy_lump_sum": _num(p.redundancy_lump_sum),
                "redundancy_target_asset": p.redundancy_target_asset or "",
                "benefits_floor_monthly": _num(p.benefits_floor_monthly),
                "benefits_delay_months": p.benefits_delay_months,
            }
            for p in household.people
        ],
        "flows": [
            {
                "kind": f.kind.value,
                "name": f.name,
                "monthly_amount": _num(f.monthly_amount),
                "owner": f.owner or "",
                "job_linked": f.job_linked,
            }
            for f in household.flows
        ],
        "assets": [
            {
                "name": a.name,
                "value": _num(a.value),
                "access_days": a.access_days,
                "haircut_pct": _num(a.haircut_pct),
            }
            for a in household.assets
        ],
        "debts": [
            {
                "name": d.name,
                "balance": _num(d.balance),
                "minimum_monthly_payment": _num(d.minimum_monthly_payment),
            }
            for d in household.debts
        ],
    }
    return tomli_w.dumps(doc)


def from_toml(text: str) -> Household:
    doc = tomllib.loads(text)
    meta = doc.get("meta", {})
    assumptions = doc.get("assumptions", {})

    people = tuple(
        Person(
            name=p["name"],
            notice_period_months=int(p.get("notice_period_months", 0)),
            redundancy_lump_sum=_dec(p.get("redundancy_lump_sum", 0)),
            redundancy_target_asset=p.get("redundancy_target_asset") or None,
            benefits_floor_monthly=_dec(p.get("benefits_floor_monthly", 0)),
            benefits_delay_months=int(p.get("benefits_delay_months", 0)),
        )
        for p in doc.get("people", [])
    )
    flows = tuple(
        Flow(
            name=f["name"],
            kind=FlowKind(f["kind"]),
            monthly_amount=_dec(f["monthly_amount"]),
            owner=f.get("owner") or None,
            job_linked=bool(f.get("job_linked", False)),
        )
        for f in doc.get("flows", [])
    )
    assets = tuple(
        Asset(
            name=a["name"],
            value=_dec(a["value"]),
            access_days=int(a["access_days"]),
            haircut_pct=_dec(a.get("haircut_pct", 0)),
        )
        for a in doc.get("assets", [])
    )
    debts = tuple(
        Debt(
            name=d["name"],
            balance=_dec(d["balance"]),
            minimum_monthly_payment=_dec(d["minimum_monthly_payment"]),
        )
        for d in doc.get("debts", [])
    )

    return Household(
        people=people,
        flows=flows,
        assets=assets,
        debts=debts,
        currency_label=meta.get("currency_label", ""),
        horizon_months=int(meta.get("horizon_months", 24)),
        major_expense_amount=_dec(assumptions.get("major_expense_amount", 3000)),
        major_expense_label=assumptions.get("major_expense_label", "Boiler / major home repair"),
        income_reduction_factor=_dec(assumptions.get("income_reduction_factor", "0.5")),
    )
