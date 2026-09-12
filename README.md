# premortem

[![tests](https://github.com/urosdrnovsek/premortem/actions/workflows/tests.yml/badge.svg)](https://github.com/urosdrnovsek/premortem/actions/workflows/tests.yml)

*A fortune teller for your bank account — minus the crystal ball, plus a spreadsheet's worth of decimal precision.*

The world is unpredictable. Layoffs happen. Boilers die at 2am in January. A client disappears. Most of us cope with this by not thinking about it too hard — which works fine, right up until it doesn't.

`premortem` is a small personal project that does the thinking for you, in advance, so you're not doing it for the first time at 3am mid-panic. Answer a few honest questions about your income, expenses, assets, and debts, and it tells you — in months, precisely — how long you'd actually last against five specific bad days: losing your job, a major unplanned expense, your income quietly shrinking, someone else in the household losing their job, or several of these ganging up on you at once (the "cold winter" scenario).

It's not a budgeting app, and it doesn't care about your net worth. It asks one blunt question — *if the bad thing happens, when do you run out of money to cover rent?* — and answers it by actually simulating your assets draining in the order you could truly reach them, because "I have savings" and "I can spend that money this month" are not the same sentence.

Debts are modelled as a minimum monthly payment against a balance, amortized with no interest. A real loan's balance falls slower than that, so this simulation can have the payment drop out — and runway look better — sooner than it would in reality.

## Sample output

![Sample report page, generated from fictional data](docs/sample-report.png)

*(Jamie, Sam, and their finances are entirely made up for this screenshot — this repo never ships or commits real household data.)*

## How it works

1. `./install.sh` — one-time setup: system libraries + a Python virtual environment.
2. `./run.sh elicit` — a guided terminal wizard asks about your household and saves it to a `.toml` file.
3. `./run.sh report your-household.toml -o report.pdf` — turns that file into a one-page PDF like the one above.

Everything runs locally. `.gitignore` refuses to let a real household file or a generated PDF anywhere near a commit, on purpose.

## Why this exists

A small, for-fun side project — an attempt to turn "I should really think about what would happen if..." into an actual number instead of a background hum of anxiety. If it's useful to you too, even better.

---

Built by [Uroš Drnovšek](https://github.com/urosdrnovsek).
