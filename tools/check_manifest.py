"""Report the UAC execution level embedded in a built executable.

The application manifest is stored as a plain UTF-8 blob in the ``.rsrc``
section, so the execution level is read by scanning that section rather than by
walking the (variable depth) resource directory tree.

    python tools/check_manifest.py dist/ApexDNSChanger.exe
"""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

LEVEL_PATTERN = re.compile(rb'requestedExecutionLevel\s+level="([^"]+)"')
SECTION_PATTERN = re.compile(rb"\.rsrc\x00", re.IGNORECASE)


def _sections(pe: bytes) -> list[tuple[str, int, int]]:
    pe_offset = struct.unpack_from("<I", pe, 0x3C)[0]
    coff = pe_offset + 4
    count = struct.unpack_from("<H", pe, coff + 2)[0]
    optional_size = struct.unpack_from("<H", pe, coff + 16)[0]
    table = pe_offset + 24 + optional_size
    found = []
    for index in range(count):
        base = table + 40 * index
        name = pe[base : base + 8].rstrip(b"\x00").decode("ascii", "replace")
        _vsize, _vaddr, raw_size, raw_offset = struct.unpack_from("<IIII", pe, base + 8)
        found.append((name, raw_offset, raw_size))
    return found


def resource_bytes(path: Path) -> bytes:
    pe = path.read_bytes()
    if pe[:2] != b"MZ":
        raise ValueError(f"{path} is not a PE executable")
    pe_offset = struct.unpack_from("<I", pe, 0x3C)[0]
    if pe[pe_offset : pe_offset + 4] != b"PE\x00\x00":
        raise ValueError("Invalid PE signature")
    for name, raw_offset, raw_size in _sections(pe):
        if name == ".rsrc":
            return pe[raw_offset : raw_offset + raw_size]
    raise ValueError("Executable has no .rsrc section")


def execution_level(path: Path) -> str:
    blob = resource_bytes(path)
    match = LEVEL_PATTERN.search(blob)
    return match.group(1).decode("ascii") if match else "absent"


def has_manifest_xml(path: Path) -> bool:
    return b"<assembly" in resource_bytes(path)


EXPECTED = {
    "ApexDNSChanger.exe": "requireAdministrator",
    "ApexDNSDiagnostics.exe": "asInvoker",
}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    failures = 0
    for raw in argv:
        path = Path(raw)
        try:
            level = execution_level(path)
        except Exception as exc:
            print(f"FAIL {path.name}: {exc}")
            failures += 1
            continue

        expected = EXPECTED.get(path.name)
        if expected and level != expected:
            print(f"FAIL {path.name}: level={level}, expected {expected}")
            failures += 1
        elif expected:
            print(f"OK   {path.name}: requestedExecutionLevel={level}")
        else:
            print(f"INFO {path.name}: requestedExecutionLevel={level}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
