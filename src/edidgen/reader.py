"""Diagnostics collection and typed readers for raw TOML tables."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from edidgen.tables import ROOT_KEYS


Table = Mapping[str, object]


@dataclass
class Diagnostics:
    """Problems found while validating a config.

    - errors: the config can't be encoded (bad types, typos, values that don't fit).
    - violations: encodable but not spec-conformant. Errors by default; with
      `allow_invalid` they are kept in `allowed_violations` and don't block output.
    - warnings: inconsistencies that still give a usable EDID.
    """

    allow_invalid: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    allowed_violations: list[str] = field(default_factory=list)
    blocking_violations: int = 0

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def violation(self, where: str, msg: str) -> None:
        if self.allow_invalid:
            self.allowed_violations.append(f"{where}: {msg}")
        else:
            self.errors.append(f"{where}: {msg}")
            self.blocking_violations += 1

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


def _type_name(value: object) -> str:
    return {
        bool: "boolean",
        int: "integer",
        float: "float",
        str: "string",
        list: "array",
        dict: "table",
    }.get(type(value), type(value).__name__)


class Reader:
    """Reads typed values out of one TOML table, recording errors in `diag`.

    On any error the default is returned, so validation can continue and
    report every problem in one run.
    """

    def __init__(self, table: Table, path: str, diag: Diagnostics) -> None:
        self.table = table
        self.path = path
        self.diag = diag
        self.seen: set[str] = set()

    def where(self, key: str) -> str:
        return f"{self.path}.{key}" if self.path else key

    def has(self, key: str) -> bool:
        return key in self.table

    def _raw(self, key: str) -> object | None:
        self.seen.add(key)
        return self.table.get(key)

    def integer(self, key: str, default: int, lo: int, hi: int) -> int:
        v = self._raw(key)
        if v is None:
            return default
        if isinstance(v, bool) or not isinstance(v, int):
            self.diag.error(self.where(key), f"expected integer, got {_type_name(v)}")
            return default
        if not lo <= v <= hi:
            self.diag.error(self.where(key), f"must be between {lo} and {hi} (got {v})")
            return default
        return v

    def number(self, key: str, default: float, lo: float, hi: float) -> float:
        v = self._raw(key)
        if v is None:
            return default
        if isinstance(v, bool) or not isinstance(v, int | float):
            self.diag.error(self.where(key), f"expected number, got {_type_name(v)}")
            return default
        if not lo <= v <= hi:
            self.diag.error(
                self.where(key), f"must be between {lo:g} and {hi:g} (got {v:g})"
            )
            return default
        return float(v)

    def boolean(self, key: str, *, default: bool) -> bool:
        v = self._raw(key)
        if v is None:
            return default
        if not isinstance(v, bool):
            self.diag.error(
                self.where(key), f"expected true/false, got {_type_name(v)}"
            )
            return default
        return v

    def string(self, key: str, default: str) -> str:
        v = self._raw(key)
        if v is None:
            return default
        if not isinstance(v, str):
            self.diag.error(self.where(key), f"expected string, got {_type_name(v)}")
            return default
        return v

    def choice(self, key: str, default: str, choices: Sequence[str]) -> str:
        v = self.string(key, default)
        if v not in choices:
            self.diag.error(
                self.where(key),
                f"must be one of {', '.join(map(repr, choices))} (got {v!r})",
            )
            return default
        return v

    def int_list(self, key: str, lo: int, hi: int) -> list[int] | None:
        v = self._raw(key)
        if v is None:
            return None
        if not isinstance(v, list):
            self.diag.error(
                self.where(key), f"expected array of integers, got {_type_name(v)}"
            )
            return None
        out: list[int] = []
        for i, item in enumerate(v):
            w = f"{self.where(key)}[{i}]"
            if isinstance(item, bool) or not isinstance(item, int):
                self.diag.error(w, f"expected integer, got {_type_name(item)}")
            elif not lo <= item <= hi:
                self.diag.error(w, f"must be between {lo} and {hi} (got {item})")
            else:
                out.append(item)
        return out

    def int_pair(self, key: str, lo: int, hi: int) -> tuple[int, int] | None:
        """A [min, max] or [a, b] array of exactly two integers."""
        n_before = len(self.diag.errors)
        values = self.int_list(key, lo, hi)
        if values is None or len(self.diag.errors) != n_before:
            return None
        if len(values) != 2:
            self.diag.error(
                self.where(key), f"expected exactly 2 values, got {len(values)}"
            )
            return None
        return values[0], values[1]

    def table_(self, key: str) -> Reader:
        v = self._raw(key)
        if v is None:
            return Reader({}, self.where(key), self.diag)
        if not isinstance(v, dict):
            self.diag.error(self.where(key), f"expected table, got {_type_name(v)}")
            return Reader({}, self.where(key), self.diag)
        return Reader(v, self.where(key), self.diag)

    def table_list(self, key: str) -> list[Reader]:
        v = self._raw(key)
        if v is None:
            return []
        if not isinstance(v, list) or not all(isinstance(t, dict) for t in v):
            self.diag.error(self.where(key), f"expected an array of tables ([[{key}]])")
            return []
        return [
            Reader(t, f"{self.where(key)}[{i}]", self.diag) for i, t in enumerate(v)
        ]

    def finish(self) -> None:
        """Report keys that were never read (usually typos)."""
        for key in self.table:
            if key in self.seen:
                continue
            msg = "unknown option"
            if self.path and key in ROOT_KEYS:
                msg += (
                    f"; `{key}` is a top-level option. In TOML, keys after a [table] or "
                    "[[table]] header belong to that table, so move it above the first header"
                )
            self.diag.error(self.where(key), msg)
