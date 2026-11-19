"""End-to-end CLI behaviour: exit codes, output paths, and what gets written."""

import runpy
import shutil
from typing import TYPE_CHECKING

import pytest
from helpers import EXAMPLE_TOML, GOLDEN_BIN, MINIMAL

from edidgen.cli import main


if TYPE_CHECKING:
    from pathlib import Path


def write(tmp_path: Path, text: str, name: str = "cfg.toml") -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def test_writes_next_to_config_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = write(tmp_path, MINIMAL)
    assert main([str(cfg)]) == 0
    out = tmp_path / "cfg.bin"
    assert len(out.read_bytes()) == 256
    stdout = capsys.readouterr().out
    assert "valid (1 detailed modes, 1 VICs)" in stdout
    assert f"wrote {out}" in stdout


def test_output_key_is_relative_to_config(tmp_path: Path) -> None:
    cfg = write(tmp_path, 'output = "named.bin"\n' + MINIMAL)
    assert main([str(cfg)]) == 0
    assert (tmp_path / "named.bin").exists()


def test_output_flag_overrides_config(tmp_path: Path) -> None:
    out = tmp_path / "flag.bin"
    assert main([str(EXAMPLE_TOML), "-o", str(out)]) == 0
    assert out.read_bytes() == GOLDEN_BIN.read_bytes()


def test_check_does_not_write(tmp_path: Path) -> None:
    cfg = write(tmp_path, MINIMAL)
    assert main([str(cfg), "--check"]) == 0
    assert not (tmp_path / "cfg.bin").exists()


def test_errors_exit_1_and_write_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = write(tmp_path, 'vics = [200]\n[display]\nmanufacturer = "x"\n')
    assert main([str(cfg)]) == 1
    assert not (tmp_path / "cfg.bin").exists()
    err = capsys.readouterr().err
    assert f"{cfg}: error: vics[0]: VIC 200" in err
    assert f"{cfg}: error: display.manufacturer" in err
    assert "3 errors; no file written." in err


def test_warnings_are_printed_but_file_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = write(
        tmp_path, MINIMAL + "[[modes]]\nwidth = 1920\nheight = 1080\nrefresh = 60\n"
    )
    assert main([str(cfg)]) == 0
    assert "warning: modes[1]" in capsys.readouterr().err
    assert (tmp_path / "cfg.bin").exists()


def test_toml_syntax_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = write(tmp_path, "[display\n")
    assert main([str(cfg)]) == 1
    assert "TOML syntax error" in capsys.readouterr().err


def test_missing_config_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "nope.toml")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_unwritable_output_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = write(tmp_path, MINIMAL)
    assert main([str(cfg), "-o", str(tmp_path / "missing-dir" / "x.bin")]) == 2
    assert "cannot write" in capsys.readouterr().err


def test_help_exits_0() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_python_dash_m(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["edidgen", str(EXAMPLE_TOML), "--check"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("edidgen", run_name="__main__")
    assert exc.value.code == 0


def test_decode_without_edid_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("edidgen.cli.shutil.which", lambda _name: None)
    assert main([str(write(tmp_path, MINIMAL)), "--decode"]) == 0
    assert "edid-decode not installed; skipping" in capsys.readouterr().err
    assert (tmp_path / "cfg.bin").exists()


@pytest.mark.skipif(
    shutil.which("edid-decode") is None, reason="edid-decode not installed"
)
def test_decode_runs_edid_decode(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    assert main([str(write(tmp_path, MINIMAL)), "--decode"]) == 0
    assert "EDID conformity:" in capfd.readouterr().out


TMDS_VIOLATION = "vics = []\n[[modes]]\nwidth = 2560\nheight = 1440\nrefresh = 120\n"


def test_violation_points_to_allow_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = write(tmp_path, TMDS_VIOLATION)
    assert main([str(cfg)]) == 1
    err = capsys.readouterr().err
    assert "1 error; no file written." in err
    assert (
        "--allow-invalid would write the EDID anyway (these are spec violations)."
        in err
    )
    assert not (tmp_path / "cfg.bin").exists()


def test_allow_invalid_writes_and_labels_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = write(tmp_path, TMDS_VIOLATION)
    assert main([str(cfg), "--allow-invalid"]) == 0
    out, err = capsys.readouterr()
    assert "invalid (allowed): modes[0]: 2560x1440@120.00 needs 497.75 MHz" in err
    assert "INVALID (1 allowed violation)" in out
    edid = (tmp_path / "cfg.bin").read_bytes()
    assert (
        int.from_bytes(edid[54:56], "little") == 49775
    )  # the over-limit mode is there


def test_hint_counts_only_violations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # One real error (name type) and one field-level violation (inverted range).
    text = (
        "vics = []\n[display]\nname = 1\n[range]\nvrefresh_hz = [120, 24]\n"
        + MINIMAL.split("\n", 1)[1]
    )
    assert main([str(write(tmp_path, text))]) == 1
    err = capsys.readouterr().err
    assert "2 errors; no file written." in err
    assert (
        "1 of these is a spec violation that --allow-invalid accepts; the rest must be fixed."
        in err
    )


def test_allow_invalid_does_not_bypass_real_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = write(tmp_path, '[display]\nname = "this is far too long"\n' + MINIMAL)
    assert main([str(cfg), "--allow-invalid"]) == 1
    err = capsys.readouterr().err
    assert "display.name: must be 1-13 printable ASCII characters" in err
    assert "allow-invalid" not in err.split("no file written.")[1]
