#!/usr/bin/env python3
"""Verify the checked-in en/ru catalogs without Xcode or third-party packages.

The source scanner covers the project's explicit localization wrappers, plus
its enumerated CSV/error/PDF keys. It is not a general Swift syntax analyzer.
New dynamic lookup sites must be enumerated here instead of silently skipped.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import plistlib
import re

LANGUAGES = ("en", "ru")
FORMS = ("one", "few", "many", "other")
QUOTED = r'"(?:\\.|[^"\\])*"'
TRIVIA = re.compile(r"\s+|//[^\n]*(?:\n|$)|/\*.*?\*/", re.DOTALL)
ENTRY = re.compile(rf"({QUOTED})\s*=\s*({QUOTED})\s*;", re.DOTALL)
FORMAT = re.compile(
    r"%(?:(?P<position>[1-9][0-9]*)\$)?[-+ #0']*"
    r"(?P<width>\*(?:[1-9][0-9]*\$)?|[0-9]+)?"
    r"(?:\.(?P<precision>\*(?:[1-9][0-9]*\$)?|[0-9]+))?"
    r"(?P<length>hh|ll|[hlLzjtq])?(?P<type>[@diuoxXfFeEgGaAcCsSpn%])"
)
# Brands and a standardized hash name deliberately do not change with language.
IDENTICAL_ALLOWED = {
    ("UI", "Room Inventory"), ("UI", "Room Inventory Pro"),
    ("InfoPlist", "CFBundleDisplayName"), ("Core", "csv.sha256"),
}


class LocalizationError(ValueError):
    pass


def quoted_value(raw: str, source: str) -> str:
    # Catalogs use quoted .strings entries with JSON-compatible escapes.
    # Also accept the conventional four-digit Apple Unicode escape.
    raw = re.sub(r"(?<!\\)\\U([0-9a-fA-F]{4})", r"\\u\1", raw)
    try:
        return json.loads(raw)
    except ValueError as error:
        raise LocalizationError(f"{source}: invalid quoted string: {error}") from error


def parse_catalog(path: Path) -> dict[str, str]:
    source = path.read_text(encoding="utf-8-sig")
    values: dict[str, str] = {}
    offset = 0
    while offset < len(source):
        trivia = TRIVIA.match(source, offset)
        if trivia:
            offset = trivia.end()
            continue
        match = ENTRY.match(source, offset)
        line = source.count("\n", 0, offset) + 1
        if not match:
            raise LocalizationError(f"{path}:{line}: expected a quoted key = value; entry")
        key = quoted_value(match[1], str(path))
        value = quoted_value(match[2], str(path))
        if key in values:
            raise LocalizationError(f"{path}:{line}: duplicate key {key!r}")
        if not key or not value.strip():
            raise LocalizationError(f"{path}:{line}: empty key or translation")
        values[key] = value
        offset = match.end()
    if not values:
        raise LocalizationError(f"{path}: empty catalog")
    return values


def format_arguments(value: str) -> dict[int, str]:
    """Compare argument identities/types, allowing positional reordering."""
    arguments: dict[int, str] = {}
    sequential = 1
    modes: set[str] = set()

    def add(position: str | None, kind: str) -> None:
        nonlocal sequential
        modes.add("positioned" if position else "sequential")
        index = int(position) if position else sequential
        if not position:
            sequential += 1
        if index in arguments and arguments[index] != kind:
            raise LocalizationError(f"conflicting types for format argument {index}")
        arguments[index] = kind

    for match in FORMAT.finditer(value):
        if match["type"] == "%":
            continue
        for name in ("width", "precision"):
            star = match[name]
            if star and star.startswith("*"):
                add(star[1:-1] if star.endswith("$") else None, "d")
        add(match["position"], (match["length"] or "") + match["type"])
    if len(modes) > 1:
        raise LocalizationError("mixed positional and sequential format arguments")
    return arguments


def validate_pair(table: str, english: dict[str, str], russian: dict[str, str]) -> None:
    missing = sorted(english.keys() - russian.keys())
    extra = sorted(russian.keys() - english.keys())
    if missing or extra:
        raise LocalizationError(f"{table}: en/ru keys differ; missing ru={missing}, missing en={extra}")
    for key, original in english.items():
        translated = russian[key]
        if not translated.strip():
            raise LocalizationError(f"{table}: empty Russian translation for {key!r}")
        if format_arguments(original) != format_arguments(translated):
            raise LocalizationError(f"{table}: format argument mismatch for {key!r}")
        if original == translated and (table, key) not in IDENTICAL_ALLOWED:
            # Punctuation-only composition templates do not need translated words.
            words = FORMAT.sub("", original)
            if any(character.isalpha() for character in words):
                raise LocalizationError(f"{table}: untranslated Russian value for {key!r}")


def swift_source(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    # Preserve string literals while removing comments from reference scanning.
    return re.sub(rf"{QUOTED}|//[^\n]*|/\*.*?\*/", lambda m: m[0] if m[0].startswith('"') else " ", text, flags=re.DOTALL)


def literal_calls(source: str, pattern: str, path: Path) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for call in re.finditer(pattern, source):
        tail = source[call.end():]
        literal = re.match(QUOTED, tail)
        if not literal or not re.match(r"\s*[,)]", tail[literal.end():]):
            raise LocalizationError(f"{path}: unenumerated dynamic localization call at {call[0]!r}")
        result.append((call[1], quoted_value(literal[0], str(path))))
    return result


def required_keys(root: Path) -> dict[str, set[str]]:
    required = {table: set() for table in ("UI", "Services", "Export", "InfoPlist", "Core")}
    for path in (root / "App").rglob("*.swift"):
        source = swift_source(path)
        for wrapper, table in (("UIL10n", "UI"), ("ServiceL10n", "Services")):
            for method, key in literal_calls(source, rf"\b{wrapper}\.(text|format|count|plural)\(\s*", path):
                if method in {"count", "plural"}:
                    required[table].update(key + "." + form for form in FORMS)
                else:
                    required[table].add(key)
        # PDF's two dynamic lookups have bounded input sets, enumerated below.
        if path.name == "ExportService.swift":
            source = source.replace("l10n.text(label)", 'l10n.text("model")')
            source = source.replace("l10n.text(attachment.kind.rawValue)", 'l10n.text("photo")')
            required["Export"].update(re.findall(r'\("([a-z]+)",\s*(?:item\.|InventoryDisplay\.)', source))
        for _, key in literal_calls(source, r"(?:\bExportL10n\(\)|\bl10n)\.(text|format)\(\s*", path):
            required["Export"].add(key)

    core = root / "Core/Sources/InventoryCore"
    errors = swift_source(core / "InventoryError.swift")
    required["Core"].update(re.findall(r'"((?:error|limit|operation)\.[A-Za-z]+)"', errors))
    csv = swift_source(core / "InventoryCSV.swift")
    header_array = re.search(r"\bheaders\s*=\s*\[([^\]]+)\]", csv, re.DOTALL)
    if not header_array:
        raise LocalizationError("Cannot enumerate CSV header localization keys")
    headers = re.findall(r'"([a-z_]+)"', header_array[1])
    required["Core"].update("csv." + header for header in headers)
    for path in core.glob("*.swift"):
        if path.name == "InventoryLocalization.swift":
            continue  # The generic engine receives already-checked keys.
        source = swift_source(path)
        if path.name == "InventoryCSV.swift":
            source = source.replace('InventoryLocalization.text("csv." + $0,', 'InventoryLocalization.text("csv.home_id",')
            source = source.replace('InventoryLocalization.text("kind." + $0.rawValue,', 'InventoryLocalization.text("kind.photo",')
        elif path.name == "InventoryError.swift":
            # The private error helpers receive the literal keys and bounded maps
            # collected above. Other dynamic Core calls must be added explicitly.
            source = re.sub(r'InventoryLocalization\.(text|format)\(key,', r'InventoryLocalization.\1("error.invalidManifest",', source)
        for method, key in literal_calls(source, r"\bInventoryLocalization\.(text|format|plural)\(\s*", path):
            if method == "plural":
                required["Core"].update(key + "." + form for form in FORMS)
            else:
                required["Core"].add(key)
    model = swift_source(core / "Models.swift")
    kinds = re.search(r"enum\s+AttachmentKind\b[^\{]*\{\s*case\s+([^\}]+)\}", model)
    if not kinds:
        raise LocalizationError("Cannot enumerate attachment kind localization keys")
    names = [name.strip() for name in kinds[1].strip().split(",")]
    if any(not re.fullmatch(r"[A-Za-z]+", name) for name in names):
        raise LocalizationError("AttachmentKind cases changed; update localization enumeration")
    required["Core"].update("kind." + name for name in names)
    required["Export"].update(names)
    required["InfoPlist"].update({"NSCameraUsageDescription", "CFBundleDisplayName", "Room Inventory Backup"})
    return required


def validate_metadata(root: Path) -> None:
    with (root / "App/Info.plist").open("rb") as source:
        info = plistlib.load(source)
    if info.get("CFBundleDevelopmentRegion") != "en" or set(info.get("CFBundleLocalizations", [])) != set(LANGUAGES):
        raise LocalizationError("App/Info.plist must declare English fallback and en/ru localizations")
    project = (root / "project.yml").read_text()
    for name in ("developmentLanguage", "CFBundleDevelopmentRegion"):
        if not re.search(rf"^\s*{name}:\s*en\s*$", project, re.MULTILINE):
            raise LocalizationError(f"project.yml must persist {name}: en")
    localizations = re.search(r"^\s*CFBundleLocalizations:\s*\[([^\]]+)\]\s*$", project, re.MULTILINE)
    if not localizations or {part.strip().strip('\"\'') for part in localizations[1].split(",")} != set(LANGUAGES):
        raise LocalizationError("project.yml must persist en/ru CFBundleLocalizations")
    package = (root / "Core/Package.swift").read_text()
    if not re.search(r'defaultLocalization:\s*"en"', package) or not re.search(r'\.process\("Resources"\)', package):
        raise LocalizationError("Core must declare English fallback and processed localization resources")


def verify(root: Path) -> dict[str, int]:
    catalogs: dict[str, dict[str, dict[str, str]]] = {}
    for directory, expected in ((root / "App/Resources", {"UI", "Services", "Export", "InfoPlist"}),
                                (root / "Core/Sources/InventoryCore/Resources", {"Core"})):
        for language in LANGUAGES:
            paths = sorted((directory / f"{language}.lproj").glob("*.strings"))
            if {path.stem for path in paths} != expected:
                raise LocalizationError(f"{directory}/{language}.lproj: expected tables {sorted(expected)}")
            for path in paths:
                catalogs.setdefault(path.stem, {})[language] = parse_catalog(path)
    for table, translations in catalogs.items():
        validate_pair(table, translations["en"], translations["ru"])
    validate_metadata(root)
    required = required_keys(root)
    for table, keys in required.items():
        for language in LANGUAGES:
            missing = sorted(keys - catalogs[table][language].keys())
            if missing:
                raise LocalizationError(f"{table}/{language}: missing referenced keys {missing}")
    return {table: len(translations["en"]) for table, translations in sorted(catalogs.items())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        counts = verify(args.root)
    except (LocalizationError, OSError, plistlib.InvalidFileException) as error:
        raise SystemExit(f"Localization verification failed: {error}") from error
    print("Localization catalogs and references passed: " + ", ".join(f"{table}={count}" for table, count in counts.items()))


if __name__ == "__main__":
    main()
