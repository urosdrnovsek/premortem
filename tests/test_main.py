from pathlib import Path

import main


FIXTURE = Path(__file__).parent / "fixtures" / "sample_household.toml"


def test_report_rejects_invalid_household_with_a_message_not_a_traceback(tmp_path, capsys):
    # A household file saved before income owners were required must fail loudly
    # (it was silently miscounted before), but as one line of text on stderr.
    bad = tmp_path / "unowned.household.toml"
    bad.write_text(FIXTURE.read_text().replace('owner = "Alex"', 'owner = ""', 1))

    rc = main.main(["report", str(bad), "-o", str(tmp_path / "out.pdf")])

    assert rc == 1
    err = capsys.readouterr().err
    assert "invalid data" in err
    assert "income must have an owner" in err
    assert "Traceback" not in err
