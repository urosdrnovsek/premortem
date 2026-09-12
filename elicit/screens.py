"""Every screen here does one thing: collect some answers and dismiss() them.
No screen imports shocks.py or runway.py - elicit/'s only output is a TOML file.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Input, Label, Select, Static


class WelcomeScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Static(
            "[b]premortem[/b]\n\n"
            "It's eighteen months from now and your household is in serious trouble.\n"
            "What happened?\n\n"
            "This walkthrough separates what you actually spend from what you think\n"
            "you spend, then tells you how many months of runway you have against\n"
            "five specific bad things - not a rule-of-thumb number you read once.",
            id="welcome-text",
        )
        yield Button("Begin", id="begin", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class PeopleCountScreen(Screen[int]):
    def compose(self) -> ComposeResult:
        yield Static("How many adults' finances does this household combine?")
        yield Button("Just me (1)", id="one")
        yield Button("Me and a partner (2)", id="two")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(1 if event.button.id == "one" else 2)


class PersonScreen(Screen[dict]):
    def __init__(self, index: int, default_name: str) -> None:
        super().__init__()
        self.index = index
        self.default_name = default_name

    def compose(self) -> ComposeResult:
        yield Static(f"[b]Person {self.index}[/b]")
        yield Label("Name")
        yield Input(value=self.default_name, id="name")
        yield Label("Notice period if made redundant (months, 0 if none/unknown)")
        yield Input(value="1", id="notice_period_months")
        yield Label("Redundancy lump sum you'd actually receive (0 if none)")
        yield Input(value="0", id="redundancy_lump_sum")
        yield Label("A benefits floor you could rely on monthly, once it starts (0 if unsure)")
        yield Input(value="0", id="benefits_floor_monthly")
        yield Label("Delay before that benefit starts, in months (from job loss)")
        yield Input(value="3", id="benefits_delay_months")
        yield Static("", id="error")
        yield Button("Continue", id="continue", variant="primary")
        yield Footer()

    NON_NEGATIVE_FIELDS = (
        "notice_period_months",
        "redundancy_lump_sum",
        "benefits_floor_monthly",
        "benefits_delay_months",
    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        try:
            result = {
                "name": self.query_one("#name", Input).value.strip() or self.default_name,
                "notice_period_months": int(self.query_one("#notice_period_months", Input).value),
                "redundancy_lump_sum": Decimal(self.query_one("#redundancy_lump_sum", Input).value),
                "benefits_floor_monthly": Decimal(self.query_one("#benefits_floor_monthly", Input).value),
                "benefits_delay_months": int(self.query_one("#benefits_delay_months", Input).value),
            }
        except (InvalidOperation, ValueError):
            self.query_one("#error", Static).update("[red]Please enter plain numbers (e.g. 1200 or 0).[/red]")
            return
        for field_name in self.NON_NEGATIVE_FIELDS:
            if result[field_name] < 0:
                self.query_one("#error", Static).update(
                    f"[red]'{field_name.replace('_', ' ')}' must be 0 or more, got {result[field_name]}.[/red]"
                )
                return
        self.dismiss(result)


FIELD_DECIMAL = "decimal"
FIELD_INT = "int"
FIELD_STR = "str"
FIELD_BOOL = "bool"


class RepeatingFormScreen(Screen[list]):
    """Collects zero or more items sharing the same small form (flows, assets, debts)."""

    def __init__(
        self,
        title: str,
        guidance: str,
        fields: list[tuple[str, str, str, str]],
        reference_names: dict[str, list[str]] | None = None,
        bounds: dict[str, tuple[Decimal | int | None, Decimal | int | None]] | None = None,
    ) -> None:
        super().__init__()
        self.title_text = title
        self.guidance = guidance
        self.fields = fields  # (key, label, kind, default)
        self.reference_names = reference_names or {}  # field key -> names it must match, if given
        self.bounds = bounds or {}  # field key -> (min, max), either may be None
        self.items: list[dict] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(f"[b]{self.title_text}[/b]\n{self.guidance}")
            for key, label, kind, default in self.fields:
                yield Label(label)
                if kind == FIELD_BOOL:
                    yield Checkbox(value=(default == "True"), id=f"field-{key}")
                else:
                    yield Input(value=default, id=f"field-{key}")
            yield Static("", id="error")
            yield Static("", id="added-count")
            with Horizontal():
                yield Button("Add another", id="add")
                yield Button("Continue", id="continue", variant="primary")
        yield Footer()

    def _read_form(self) -> dict | None:
        result: dict = {}
        for key, label, kind, default in self.fields:
            if kind == FIELD_BOOL:
                result[key] = self.query_one(f"#field-{key}", Checkbox).value
                continue
            raw = self.query_one(f"#field-{key}", Input).value.strip()
            if kind == FIELD_STR:
                valid_names = self.reference_names.get(key)
                if valid_names is not None and raw and raw not in valid_names:
                    self.query_one("#error", Static).update(
                        f"[red]'{label}' must match an existing name: {', '.join(valid_names)}.[/red]"
                    )
                    return None
                result[key] = raw
            elif kind == FIELD_DECIMAL:
                try:
                    value = Decimal(raw) if raw else Decimal("0")
                except InvalidOperation:
                    self.query_one("#error", Static).update(f"[red]'{label}' needs a plain number.[/red]")
                    return None
                bounds_error = self._bounds_error(key, label, value)
                if bounds_error:
                    self.query_one("#error", Static).update(f"[red]{bounds_error}[/red]")
                    return None
                result[key] = value
            elif kind == FIELD_INT:
                try:
                    value = int(raw) if raw else 0
                except ValueError:
                    self.query_one("#error", Static).update(f"[red]'{label}' needs a whole number.[/red]")
                    return None
                bounds_error = self._bounds_error(key, label, value)
                if bounds_error:
                    self.query_one("#error", Static).update(f"[red]{bounds_error}[/red]")
                    return None
                result[key] = value
        return result

    def _bounds_error(self, key: str, label: str, value: Decimal | int) -> str | None:
        lo, hi = self.bounds.get(key, (None, None))
        if lo is not None and value < lo:
            return f"'{label}' must be {lo} or more, got {value}."
        if hi is not None and value > hi:
            return f"'{label}' must be {hi} or less, got {value}."
        return None

    def _clear_form(self) -> None:
        for key, label, kind, default in self.fields:
            if kind == FIELD_BOOL:
                self.query_one(f"#field-{key}", Checkbox).value = (default == "True")
            else:
                self.query_one(f"#field-{key}", Input).value = default
        self.query_one("#error", Static).update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        name_key = self.fields[0][0]
        item = self._read_form()
        if item is None:
            return
        has_name = bool(item.get(name_key))

        if event.button.id == "add":
            if has_name:
                self.items.append(item)
                self._clear_form()
                self.query_one("#added-count", Static).update(f"{len(self.items)} added so far.")
            else:
                self.query_one("#error", Static).update("[red]Give it a name before adding another.[/red]")
            return

        if has_name:
            self.items.append(item)
        self.dismiss(self.items)


class AssumptionsScreen(Screen[dict]):
    def compose(self) -> ComposeResult:
        yield Static(
            "[b]Assumptions used by the five preset shocks[/b]\n"
            "These are yours to edit later by hand in the saved TOML file."
        )
        yield Label("Currency symbol/label to show on the report")
        yield Input(value="£", id="currency_label")
        yield Label("How many months forward to project")
        yield Input(value="24", id="horizon_months")
        yield Label("A major unplanned expense you could plausibly face (e.g. boiler, car, roof)")
        yield Input(value="3000", id="major_expense_amount")
        yield Label("What to call that expense on the report")
        yield Input(value="Boiler / major home repair", id="major_expense_label")
        yield Label("If income dropped but didn't stop, what fraction would remain? (0-1)")
        yield Input(value="0.5", id="income_reduction_factor")
        yield Static("", id="error")
        yield Button("Continue", id="continue", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        try:
            result = {
                "currency_label": self.query_one("#currency_label", Input).value,
                "horizon_months": int(self.query_one("#horizon_months", Input).value),
                "major_expense_amount": Decimal(self.query_one("#major_expense_amount", Input).value),
                "major_expense_label": self.query_one("#major_expense_label", Input).value,
                "income_reduction_factor": Decimal(self.query_one("#income_reduction_factor", Input).value),
            }
        except (InvalidOperation, ValueError):
            self.query_one("#error", Static).update("[red]Please enter plain numbers.[/red]")
            return
        if result["horizon_months"] < 1:
            self.query_one("#error", Static).update(
                f"[red]'How many months forward to project' must be 1 or more, got {result['horizon_months']}.[/red]"
            )
            return
        if result["major_expense_amount"] < 0:
            self.query_one("#error", Static).update(
                f"[red]'A major unplanned expense' must be 0 or more, got {result['major_expense_amount']}.[/red]"
            )
            return
        if result["income_reduction_factor"] < 0:
            self.query_one("#error", Static).update(
                f"[red]'If income dropped but didn't stop' must be 0 or more, got {result['income_reduction_factor']}.[/red]"
            )
            return
        self.dismiss(result)


class RedundancyTargetScreen(Screen[str]):
    """Which asset does this person's redundancy lump sum land in?"""

    def __init__(self, person_name: str, asset_names: list[str]) -> None:
        super().__init__()
        self.person_name = person_name
        self.asset_names = asset_names

    def compose(self) -> ComposeResult:
        yield Static(f"If {self.person_name} were made redundant, which account would the payout land in?")
        yield Select([(n, n) for n in self.asset_names], id="asset-select", value=self.asset_names[0])
        yield Button("Continue", id="continue", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(str(self.query_one("#asset-select", Select).value))


class ReviewScreen(Screen[str]):
    def __init__(self, summary: str, default_path: str) -> None:
        super().__init__()
        self.summary = summary
        self.default_path = default_path

    def compose(self) -> ComposeResult:
        yield Static(f"[b]Review[/b]\n\n{self.summary}\n")
        yield Label("Save to (path)")
        yield Input(value=self.default_path, id="path")
        yield Static("", id="error")
        yield Button("Save", id="save", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        path = self.query_one("#path", Input).value.strip()
        if not path:
            self.query_one("#error", Static).update("[red]Enter a file path.[/red]")
            return
        self.dismiss(path)
