"""End-to-end CLI behaviour: exit codes, output paths, and what gets written."""

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


def test_module_entry_point_help() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
