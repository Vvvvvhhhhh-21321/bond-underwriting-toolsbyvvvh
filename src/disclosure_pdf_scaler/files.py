from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscoveryResult:
    files: tuple[Path, ...]
    ignored_non_pdf: int
    duplicate_paths: int
    duplicate_names: tuple[str, ...]


def discover_pdfs(inputs: tuple[Path, ...]) -> DiscoveryResult:
    candidates: list[Path] = []
    ignored = 0
    for item in inputs:
        if item.is_dir():
            for child in item.rglob("*"):
                if child.is_file():
                    if child.suffix.casefold() == ".pdf":
                        candidates.append(child)
                    else:
                        ignored += 1
        elif item.suffix.casefold() == ".pdf":
            candidates.append(item)
        elif item.exists():
            ignored += 1

    seen_paths: set[str] = set()
    unique_paths: list[Path] = []
    duplicate_paths = 0
    for path in candidates:
        key = str(path.resolve()).casefold()
        if key in seen_paths:
            duplicate_paths += 1
        else:
            seen_paths.add(key)
            unique_paths.append(path.resolve())

    unique_paths.sort(key=lambda path: _natural_key(str(path)))
    seen_names: set[str] = set()
    files: list[Path] = []
    duplicate_names: list[str] = []
    for path in unique_paths:
        key = path.name.casefold()
        if key in seen_names:
            duplicate_names.append(path.name)
        else:
            seen_names.add(key)
            files.append(path)
    return DiscoveryResult(tuple(files), ignored, duplicate_paths, tuple(duplicate_names))


def _natural_key(value: str) -> tuple[object, ...]:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value))
