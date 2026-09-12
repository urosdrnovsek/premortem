"""The Textual wizard. Its only job: produce a TOML file via model.to_toml().

It deliberately never imports shocks.py or runway.py - that boundary is what
lets a hand-written TOML file work without any UI code, and what lets power
users edit their file directly instead of re-running this wizard.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from textual import work
from textual.app import App

from model import Asset, Debt, Flow, FlowKind, Household, Person, to_toml
from elicit.screens import (
    FIELD_BOOL,
    FIELD_DECIMAL,
    FIELD_INT,
    FIELD_STR,
    AssumptionsScreen,
    PeopleCountScreen,
    PersonScreen,
    RedundancyTargetScreen,
    RepeatingFormScreen,
    ReviewScreen,
    WelcomeScreen,
)

INCOME_FIELDS = [
    ("name", "Name (e.g. 'Alex: salary')", FIELD_STR, ""),
    ("owner", "Whose income is this? (must match a person's name)", FIELD_STR, ""),
    ("monthly_amount", "Net monthly amount", FIELD_DECIMAL, "0"),
]
FIXED_FIELDS = [
    ("name", "Name (rent, mortgage, insurance, minimum subscriptions...)", FIELD_STR, ""),
    ("monthly_amount", "Monthly amount", FIELD_DECIMAL, "0"),
]
VARIABLE_FIELDS = [
    ("name", "Name (groceries, fuel, streaming, commuting...)", FIELD_STR, ""),
    ("monthly_amount", "Monthly amount", FIELD_DECIMAL, "0"),
    ("job_linked", "Would this disappear if you stopped working? (commute, childcare, lunches out)", FIELD_BOOL, "False"),
]
ASSET_FIELDS = [
    ("name", "Name (current account, easy-access savings, ISA, pension...)", FIELD_STR, ""),
    ("value", "Current value", FIELD_DECIMAL, "0"),
    ("access_days", "Days until you could actually spend it (0 = instant; use 36500 for a pension you can't touch)", FIELD_INT, "0"),
    ("haircut_pct", "Fraction lost if forced to cash out early, e.g. market timing or an exit fee (0-1)", FIELD_DECIMAL, "0"),
]
DEBT_FIELDS = [
    ("name", "Name (car loan, credit card, ...)", FIELD_STR, ""),
    ("balance", "Balance owed", FIELD_DECIMAL, "0"),
    ("minimum_monthly_payment", "Minimum monthly payment", FIELD_DECIMAL, "0"),
]

# Bounds mirror the sign/range checks in model.py's __post_init__ methods, so bad
# input is caught here with the wizard's friendly error instead of crashing the
# @work worker when Flow/Asset/Debt are constructed at the end of run_wizard().
INCOME_BOUNDS = {"monthly_amount": (Decimal("0"), None)}
FIXED_BOUNDS = {"monthly_amount": (Decimal("0"), None)}
VARIABLE_BOUNDS = {"monthly_amount": (Decimal("0"), None)}
ASSET_BOUNDS = {
    "value": (Decimal("0"), None),
    "access_days": (0, None),
    "haircut_pct": (Decimal("0"), Decimal("1")),
}
DEBT_BOUNDS = {
    "balance": (Decimal("0"), None),
    "minimum_monthly_payment": (Decimal("0"), None),
}


class PremortemApp(App[None]):
    CSS = """
    Screen { align: center middle; }
    #welcome-text, VerticalScroll { padding: 1 2; }
    Input, Select { margin-bottom: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.household: Household | None = None
        self.saved_path: str | None = None

    def on_mount(self) -> None:
        self.run_wizard()

    @work
    async def run_wizard(self) -> None:
        await self.push_screen_wait(WelcomeScreen())

        num_people = await self.push_screen_wait(PeopleCountScreen())
        default_names = ["You", "Partner"]
        people_answers = []
        for i in range(num_people):
            answer = await self.push_screen_wait(PersonScreen(i + 1, default_names[i]))
            people_answers.append(answer)

        person_names = [a["name"] for a in people_answers]
        income_items = await self.push_screen_wait(
            RepeatingFormScreen(
                "Income",
                "Add each net (after-tax) income source, one at a time.",
                INCOME_FIELDS,
                reference_names={"owner": person_names},
                bounds=INCOME_BOUNDS,
            )
        )
        fixed_items = await self.push_screen_wait(
            RepeatingFormScreen(
                "Fixed costs",
                "Costs that don't change month to month and that you can't quickly cancel.",
                FIXED_FIELDS,
                bounds=FIXED_BOUNDS,
            )
        )
        variable_items = await self.push_screen_wait(
            RepeatingFormScreen(
                "Variable costs",
                "Costs you could cut or that would change if your situation changed.",
                VARIABLE_FIELDS,
                bounds=VARIABLE_BOUNDS,
            )
        )
        asset_items = await self.push_screen_wait(
            RepeatingFormScreen(
                "Assets",
                "Separate what you could spend today from what takes time or a penalty to reach.",
                ASSET_FIELDS,
                bounds=ASSET_BOUNDS,
            )
        )
        debt_items = await self.push_screen_wait(
            RepeatingFormScreen(
                "Debts",
                "Minimum payments on anything you owe - these don't stop in a shock.",
                DEBT_FIELDS,
                bounds=DEBT_BOUNDS,
            )
        )

        asset_names = [a["name"] for a in asset_items]
        redundancy_targets: dict[str, str] = {}
        for answer in people_answers:
            if answer["redundancy_lump_sum"] > 0 and asset_names:
                target = await self.push_screen_wait(
                    RedundancyTargetScreen(answer["name"], asset_names)
                )
                redundancy_targets[answer["name"]] = target
            # No assets were added: leave redundancy_target_asset unset. runway.project
            # lands an unassigned redundancy payout in an implicit same-day account
            # rather than pointing at an asset name that doesn't exist.

        assumptions = await self.push_screen_wait(AssumptionsScreen())

        people = tuple(
            Person(
                name=a["name"],
                notice_period_months=a["notice_period_months"],
                redundancy_lump_sum=a["redundancy_lump_sum"],
                redundancy_target_asset=redundancy_targets.get(a["name"]),
                benefits_floor_monthly=a["benefits_floor_monthly"],
                benefits_delay_months=a["benefits_delay_months"],
            )
            for a in people_answers
        )
        flows = tuple(
            [Flow(name=f["name"], kind=FlowKind.INCOME, monthly_amount=f["monthly_amount"], owner=f["owner"]) for f in income_items]
            + [Flow(name=f["name"], kind=FlowKind.FIXED_EXPENSE, monthly_amount=f["monthly_amount"]) for f in fixed_items]
            + [
                Flow(name=f["name"], kind=FlowKind.VARIABLE_EXPENSE, monthly_amount=f["monthly_amount"], job_linked=f["job_linked"])
                for f in variable_items
            ]
        )
        assets = tuple(
            Asset(name=a["name"], value=a["value"], access_days=a["access_days"], haircut_pct=a["haircut_pct"])
            for a in asset_items
        )
        debts = tuple(
            Debt(name=d["name"], balance=d["balance"], minimum_monthly_payment=d["minimum_monthly_payment"])
            for d in debt_items
        )

        household = Household(
            people=people,
            flows=flows,
            assets=assets,
            debts=debts,
            currency_label=assumptions["currency_label"],
            horizon_months=assumptions["horizon_months"],
            major_expense_amount=assumptions["major_expense_amount"],
            major_expense_label=assumptions["major_expense_label"],
            income_reduction_factor=assumptions["income_reduction_factor"],
        )
        self.household = household

        summary = (
            f"{len(people)} person(s), {len(flows)} flow(s), {len(assets)} asset(s), {len(debts)} debt(s).\n"
            "This will be saved as a TOML file you can re-run reports against, or edit by hand."
        )
        path = await self.push_screen_wait(ReviewScreen(summary, "household.household.toml"))
        Path(path).write_text(to_toml(household))
        self.saved_path = path
        self.exit()


if __name__ == "__main__":
    PremortemApp().run()
