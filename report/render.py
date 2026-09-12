"""Household + Projections -> a one-page PDF. Reads, never computes shocks or runway itself."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import jinja2

from model import Household, FlowKind
from runway import Projection

TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
    autoescape=jinja2.select_autoescape(["html"]),
)


def _fmt(currency: str, amount: Decimal) -> str:
    return f"{currency}{amount:,.0f}"


def _severity(insolvent_month: int | None) -> str:
    if insolvent_month is None:
        return "safe"
    if insolvent_month < 3:
        return "danger"
    return "warn"


def _months_label(insolvent_month: int | None, horizon_months: int) -> str:
    if insolvent_month is None:
        return f"Safe beyond {horizon_months} mo"
    if insolvent_month == 1:
        return "1 month"
    return f"{insolvent_month} months"


def _narrative(household: Household, projections: list[Projection]) -> str | None:
    access_days_by_asset = {a.name: a.access_days for a in household.assets}
    haircut_by_asset = {a.name: a.haircut_pct for a in household.assets}

    insolvent = [p for p in projections if p.insolvent_month is not None]
    worst = min(insolvent, key=lambda p: p.insolvent_month) if insolvent else \
        max(projections, key=lambda p: sum(len(m.draws) for m in p.months), default=None)
    if worst is None:
        return None

    for month_snapshot in worst.months:
        for draw in month_snapshot.draws:
            days = access_days_by_asset.get(draw.asset_name, 0)
            if days > 0:
                haircut = haircut_by_asset.get(draw.asset_name, Decimal("0"))
                haircut_note = (
                    f", after a {haircut * 100:.0f}% haircut for cashing out early"
                    if haircut > 0 else ""
                )
                return (
                    f"In “{worst.shock.label}”, month {month_snapshot.month}: your "
                    f"{draw.asset_name} took {days} day(s) to actually reach, contributing "
                    f"{_fmt(household.currency_label, draw.net_amount)}{haircut_note}."
                )
    return None


def build_context(household: Household, projections: list[Projection]) -> dict:
    currency = household.currency_label
    total_income = sum(
        (f.monthly_amount for f in household.flows if f.kind == FlowKind.INCOME), Decimal("0")
    )
    total_fixed = sum(
        (f.monthly_amount for f in household.flows if f.kind == FlowKind.FIXED_EXPENSE), Decimal("0")
    ) + sum((d.minimum_monthly_payment for d in household.debts), Decimal("0"))
    total_variable = sum(
        (f.monthly_amount for f in household.flows if f.kind == FlowKind.VARIABLE_EXPENSE), Decimal("0")
    )
    total_assets = sum((a.value for a in household.assets), Decimal("0"))

    shocks_rows = [
        {
            "label": p.shock.label,
            "description": p.shock.description,
            "months_label": _months_label(p.insolvent_month, household.horizon_months),
            "severity": _severity(p.insolvent_month),
        }
        for p in projections
    ]

    return {
        "generated_on": date.today().isoformat(),
        "currency": currency,
        "people": [p.name for p in household.people],
        "horizon_months": household.horizon_months,
        "total_income": _fmt(currency, total_income),
        "total_fixed": _fmt(currency, total_fixed),
        "total_variable": _fmt(currency, total_variable),
        "total_assets": _fmt(currency, total_assets),
        "shocks": shocks_rows,
        "narrative": _narrative(household, projections),
    }


def render_html(household: Household, projections: list[Projection]) -> str:
    template = _env.get_template("report.html.jinja")
    return template.render(**build_context(household, projections))


def render_pdf(household: Household, projections: list[Projection], out_path: Path) -> None:
    import weasyprint  # imported lazily: only needed for the PDF path, not for HTML/testing

    html = render_html(household, projections)
    weasyprint.HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf(str(out_path))
