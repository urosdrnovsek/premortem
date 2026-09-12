"""Headless smoke test for the Textual wizard, via Pilot - no real terminal needed."""
import asyncio
from decimal import Decimal
from pathlib import Path

from textual.widgets import Input, Checkbox, Select

from elicit.app import PremortemApp
import model


async def _fill(pilot, values: dict[str, str]) -> None:
    for field_id, value in values.items():
        widget = pilot.app.screen.query_one(f"#{field_id}")
        if isinstance(widget, Checkbox):
            widget.value = value == "True"
        elif isinstance(widget, Input):
            widget.value = value
    await pilot.pause()


async def _run_wizard(out_path: Path) -> model.Household:
    app = PremortemApp()
    async with app.run_test(size=(100, 60)) as pilot:
        await pilot.pause()
        await pilot.click("#begin")               # Welcome
        await pilot.pause()

        await pilot.click("#one")                  # PeopleCount: single adult
        await pilot.pause()

        await _fill(pilot, {                        # PersonScreen
            "name": "Solo",
            "notice_period_months": "1",
            "redundancy_lump_sum": "3000",
            "benefits_floor_monthly": "900",
            "benefits_delay_months": "2",
        })
        await pilot.click("#continue")
        await pilot.pause()

        await _fill(pilot, {"field-name": "Salary", "field-owner": "Solo", "field-monthly_amount": "2500"})
        await pilot.click("#continue")              # Income (one item then continue)
        await pilot.pause()

        await _fill(pilot, {"field-name": "Rent", "field-monthly_amount": "1000"})
        await pilot.click("#continue")               # Fixed costs
        await pilot.pause()

        await _fill(pilot, {"field-name": "Groceries", "field-monthly_amount": "300"})
        await pilot.click("#continue")               # Variable costs
        await pilot.pause()

        await _fill(pilot, {"field-name": "Current account", "field-value": "2000", "field-access_days": "0", "field-haircut_pct": "0"})
        await pilot.click("#continue")               # Assets
        await pilot.pause()

        await pilot.click("#continue")               # Debts: none, leave name blank
        await pilot.pause()

        await pilot.click("#continue")               # RedundancyTargetScreen: accept default
        await pilot.pause()

        await pilot.click("#continue")               # AssumptionsScreen: accept defaults
        await pilot.pause()

        toml_path = str(out_path)
        widget = pilot.app.screen.query_one("#path", Input)
        widget.value = toml_path
        await pilot.click("#save")                    # ReviewScreen
        await pilot.pause()

    assert app.household is not None
    return app.household


def test_wizard_produces_loadable_household(tmp_path):
    out_path = tmp_path / "smoke.household.toml"
    household = asyncio.run(_run_wizard(out_path))

    assert out_path.exists()
    reloaded = model.from_toml(out_path.read_text())
    assert reloaded == household
    assert reloaded.person("Solo").redundancy_lump_sum == Decimal("3000")
    assert reloaded.person("Solo").redundancy_target_asset == "Current account"
    assert len(reloaded.assets) == 1


async def _run_wizard_with_no_assets(out_path: Path) -> model.Household:
    """Same as _run_wizard but adds no assets - regression coverage for the
    redundancy-lump-sum-with-nowhere-to-land case: the wizard must not fabricate a
    fake target asset name, and the resulting TOML must still load and report cleanly."""
    app = PremortemApp()
    async with app.run_test(size=(100, 60)) as pilot:
        await pilot.pause()
        await pilot.click("#begin")               # Welcome
        await pilot.pause()

        await pilot.click("#one")                  # PeopleCount: single adult
        await pilot.pause()

        await _fill(pilot, {                        # PersonScreen
            "name": "Solo",
            "notice_period_months": "1",
            "redundancy_lump_sum": "3000",
            "benefits_floor_monthly": "900",
            "benefits_delay_months": "2",
        })
        await pilot.click("#continue")
        await pilot.pause()

        await _fill(pilot, {"field-name": "Salary", "field-owner": "Solo", "field-monthly_amount": "2500"})
        await pilot.click("#continue")              # Income (one item then continue)
        await pilot.pause()

        await _fill(pilot, {"field-name": "Rent", "field-monthly_amount": "1000"})
        await pilot.click("#continue")               # Fixed costs
        await pilot.pause()

        await _fill(pilot, {"field-name": "Groceries", "field-monthly_amount": "300"})
        await pilot.click("#continue")               # Variable costs
        await pilot.pause()

        await pilot.click("#continue")               # Assets: none added, leave name blank
        await pilot.pause()

        await pilot.click("#continue")               # Debts: none, leave name blank
        await pilot.pause()

        # No RedundancyTargetScreen here - with zero assets it must be skipped
        # rather than offering a fake placeholder asset name.

        await pilot.click("#continue")               # AssumptionsScreen: accept defaults
        await pilot.pause()

        toml_path = str(out_path)
        widget = pilot.app.screen.query_one("#path", Input)
        widget.value = toml_path
        await pilot.click("#save")                    # ReviewScreen
        await pilot.pause()

    assert app.household is not None
    return app.household


async def _run_wizard_with_bad_then_good_owner(out_path: Path) -> model.Household:
    """Regression coverage: an income 'owner' that is blank, or doesn't match a
    person's name, must be caught right there with the friendly red-text error,
    not crash the @work worker later when Household() cross-validates it. A
    blank owner used to pass and produce an income line no projection counted."""
    app = PremortemApp()
    async with app.run_test(size=(100, 60)) as pilot:
        await pilot.pause()
        await pilot.click("#begin")               # Welcome
        await pilot.pause()

        await pilot.click("#one")                  # PeopleCount: single adult
        await pilot.pause()

        await _fill(pilot, {"name": "Solo"})        # PersonScreen: defaults for the rest
        await pilot.click("#continue")
        await pilot.pause()

        await _fill(pilot, {"field-name": "Salary", "field-owner": "", "field-monthly_amount": "2500"})
        await pilot.click("#continue")               # Income: blank owner - must not advance
        await pilot.pause()

        error_text = str(pilot.app.screen.query_one("#error").render())
        assert "is required" in error_text

        # Button.press() ignores clicks on the same button while its "-active"
        # animation is running (active_effect_duration = 0.2s) - wait it out
        # before clicking Continue again on this same button instance.
        await pilot.pause(0.3)

        await _fill(pilot, {"field-owner": "Nobody"})
        await pilot.click("#continue")               # Income: mismatched owner - must not advance
        await pilot.pause()

        error_text = str(pilot.app.screen.query_one("#error").render())
        assert "must match an existing name" in error_text

        await pilot.pause(0.3)

        await _fill(pilot, {"field-owner": "Solo"})   # correct it and continue for real
        await pilot.click("#continue")
        await pilot.pause()

        await pilot.click("#continue")               # Fixed costs: none
        await pilot.pause()
        await pilot.click("#continue")               # Variable costs: none
        await pilot.pause()
        await pilot.click("#continue")               # Assets: none
        await pilot.pause()
        await pilot.click("#continue")               # Debts: none
        await pilot.pause()
        await pilot.click("#continue")               # AssumptionsScreen: defaults
        await pilot.pause()

        toml_path = str(out_path)
        widget = pilot.app.screen.query_one("#path", Input)
        widget.value = toml_path
        await pilot.click("#save")                    # ReviewScreen
        await pilot.pause()

    assert app.household is not None
    return app.household


def test_wizard_rejects_income_owner_not_matching_a_person(tmp_path):
    out_path = tmp_path / "bad_owner.household.toml"
    household = asyncio.run(_run_wizard_with_bad_then_good_owner(out_path))

    assert out_path.exists()
    assert household.flows[0].owner == "Solo"


async def _check_person_screen_rejects_negative_redundancy_lump_sum() -> None:
    """Regression coverage: a negative number in a Person field (e.g. redundancy
    lump sum) must be caught right there with the friendly red-text error, not
    crash the @work worker later when Person() re-validates it in model.py."""
    app = PremortemApp()
    async with app.run_test(size=(100, 60)) as pilot:
        await pilot.pause()
        await pilot.click("#begin")               # Welcome
        await pilot.pause()
        await pilot.click("#one")                  # PeopleCount: single adult
        await pilot.pause()

        await _fill(pilot, {"redundancy_lump_sum": "-500"})
        await pilot.click("#continue")               # PersonScreen: negative - must not advance
        await pilot.pause()

        error_text = str(pilot.app.screen.query_one("#error").render())
        assert "must be 0 or more" in error_text
        assert pilot.app.screen.query_one("#redundancy_lump_sum", Input).value == "-500"


async def _check_asset_form_rejects_haircut_pct_above_one() -> None:
    """Regression coverage: haircut_pct > 1 in the Assets form must be caught
    right there, not crash the @work worker later when Asset() re-validates it."""
    app = PremortemApp()
    async with app.run_test(size=(100, 60)) as pilot:
        await pilot.pause()
        await pilot.click("#begin")               # Welcome
        await pilot.pause()
        await pilot.click("#one")                  # PeopleCount: single adult
        await pilot.pause()
        await pilot.click("#continue")               # PersonScreen: defaults
        await pilot.pause()
        await pilot.click("#continue")               # Income: none
        await pilot.pause()
        await pilot.click("#continue")               # Fixed costs: none
        await pilot.pause()
        await pilot.click("#continue")               # Variable costs: none
        await pilot.pause()

        await _fill(pilot, {"field-name": "ISA", "field-haircut_pct": "1.5"})
        await pilot.click("#continue")               # Assets: out-of-range haircut - must not advance
        await pilot.pause()

        error_text = str(pilot.app.screen.query_one("#error").render())
        assert "must be 1 or less" in error_text
        assert pilot.app.screen.items == []


def test_wizard_rejects_negative_redundancy_lump_sum():
    asyncio.run(_check_person_screen_rejects_negative_redundancy_lump_sum())


def test_wizard_rejects_haircut_pct_above_one():
    asyncio.run(_check_asset_form_rejects_haircut_pct_above_one())


def test_wizard_skips_redundancy_target_when_no_assets_added(tmp_path):
    out_path = tmp_path / "no_assets.household.toml"
    household = asyncio.run(_run_wizard_with_no_assets(out_path))

    assert out_path.exists()
    reloaded = model.from_toml(out_path.read_text())
    assert reloaded == household
    assert len(reloaded.assets) == 0
    assert reloaded.person("Solo").redundancy_lump_sum == Decimal("3000")
    assert reloaded.person("Solo").redundancy_target_asset is None

    # And report generation over this household must not crash (the bug this
    # regression guards against was a KeyError/ValueError deep in runway.project).
    import runway
    import shocks
    for shock in shocks.presets(reloaded):
        runway.project(reloaded, shock)
