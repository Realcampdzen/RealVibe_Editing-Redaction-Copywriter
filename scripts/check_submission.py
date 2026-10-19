"""Check the public submission contract, never factual/editorial quality or delivery.

Python 3.9+; standard library only. No network, writes, credentials or publishing.
"""

import argparse
import json
from datetime import date, datetime
from pathlib import Path
import re
import sys


FORMATS = {"dzen_article", "social_post", "meme", "comic"}
STATUSES = {
    "draft", "ready_for_review", "in_review", "needs_revision",
    "accepted", "handed_off", "archived",
}
MEDIA = {"planned", "ready", "not_required"}
SURFACES = {"dzen", "telegram", "vk", "max", "telegram_story", "vk_story"}
REQUIRED = {
    "schema_version", "id", "title", "format", "rubric", "status", "author",
    "updated_at", "content_file", "variants", "media_status",
    "requested_publication", "is_example",
}
REPO = Path(__file__).resolve().parent.parent


def check(package):
    package = package.resolve()
    errors, warnings = [], []
    texts = {}

    def read_text(relative):
        if not isinstance(relative, str) or not relative.strip():
            errors.append("A file path must be a non-empty string.")
            return None
        try:
            path = (package / relative).resolve()
        except (OSError, ValueError) as exc:
            errors.append(f"Invalid file path: {exc}")
            return None
        try:
            path.relative_to(package)
        except ValueError:
            errors.append(f"Path escapes the package: {relative}")
            return None
        if Path(relative).is_absolute() or path.suffix.lower() != ".md":
            errors.append(f"Use a relative Markdown file path: {relative}")
            return None
        try:
            value = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            errors.append(f"Cannot read {relative}: {exc}")
            return None
        if not value.strip():
            errors.append(f"Empty file: {relative}")
        texts[relative] = value
        return value

    try:
        meta_path = (package / "meta.json").resolve()
        meta_path.relative_to(package)
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"Cannot read package meta.json: {exc}"], warnings
    if not isinstance(meta, dict):
        return ["meta.json must contain an object."], warnings

    missing = sorted(REQUIRED - set(meta))
    if missing:
        errors.append("Missing metadata: " + ", ".join(missing))
    if type(meta.get("schema_version")) is not int or meta["schema_version"] != 1:
        errors.append("schema_version must be integer 1.")
    for field in ("id", "title", "rubric", "author", "updated_at"):
        if not isinstance(meta.get(field), str) or not meta[field].strip():
            errors.append(f"{field} must be a non-empty string.")

    identity = meta.get("id")
    if isinstance(identity, str):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*", identity):
            errors.append("id must have format YYYY-MM-DD-lowercase-slug.")
        else:
            try:
                date.fromisoformat(identity[:10])
            except ValueError:
                errors.append("id contains an invalid creation date.")
        if identity != package.name:
            errors.append("id must equal the package folder name.")

    for field, allowed in (("format", FORMATS), ("status", STATUSES), ("media_status", MEDIA)):
        if not isinstance(meta.get(field), str) or meta[field] not in allowed:
            errors.append(f"Invalid {field}; allowed: {', '.join(sorted(allowed))}")
    try:
        stamp = datetime.fromisoformat(str(meta.get("updated_at", "")).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("missing timezone")
    except ValueError:
        errors.append("updated_at must be an ISO datetime with a UTC offset.")
    if type(meta.get("is_example")) is not bool:
        errors.append("is_example must be true or false.")
    if meta.get("is_example") is True:
        warnings.append("TRAINING EXAMPLE: not a working submission or release candidate.")
        if (REPO / "submissions").resolve() in package.parents:
            errors.append("Training examples belong in examples/, not submissions/.")
    if meta.get("status") in ("accepted", "handed_off") and meta.get("media_status") == "planned":
        errors.append("Accepted/handed-off material cannot still have planned media.")

    content = read_text(meta.get("content_file"))
    if content is not None:
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        if first_line != "# " + str(meta.get("title", "")):
            errors.append("The first content line must be '# ' plus the exact metadata title.")
    for filename in ("sources.md", "media.md", "review.md"):
        read_text(filename)

    variants = meta.get("variants")
    if not isinstance(variants, dict):
        errors.append("variants must be an object mapping surface names to files.")
    else:
        for surface, filename in variants.items():
            if surface not in SURFACES:
                errors.append(f"Unknown variant surface: {surface}")
            variant = read_text(filename)
            if surface == "telegram" and variant is not None:
                units = len(variant.rstrip("\r\n").encode("utf-16-le")) // 2
                if units > 1024:
                    errors.append(f"Telegram media caption is {units} UTF-16 units (limit 1024).")
                else:
                    warnings.append(f"Telegram caption file: {units}/1024 UTF-16 units; recheck the actual export.")

    request = meta.get("requested_publication")
    if request is not None:
        if not isinstance(request, dict):
            errors.append("requested_publication must be null or an object.")
        else:
            if not {"date", "timezone", "time", "surfaces"}.issubset(request):
                errors.append("Release request requires date, timezone, time and surfaces.")
            try:
                date.fromisoformat(str(request.get("date", "")))
            except ValueError:
                errors.append("Release request date must be a real YYYY-MM-DD date.")
            if not isinstance(request.get("timezone"), str) or not re.fullmatch(
                r"[A-Za-z_]+/[A-Za-z_+-]+(?:/[A-Za-z_+-]+)?", request["timezone"]
            ):
                errors.append("Use a named timezone, e.g. Europe/Moscow.")
            requested_time = request.get("time")
            if requested_time is not None and (
                not isinstance(requested_time, str)
                or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", requested_time)
            ):
                errors.append("Requested time must be null or HH:MM in 24-hour format.")
            surfaces = request.get("surfaces")
            if not isinstance(surfaces, list) or not surfaces or any(
                not isinstance(item, str) or item not in SURFACES for item in surfaces
            ):
                errors.append("Release request surfaces must be a non-empty list of supported surfaces.")
            warnings.append("A release request is not proof of a queue entry or a schedule.")

    for filename, value in {**texts, "meta.json": json.dumps(meta, ensure_ascii=False)}.items():
        if re.search(r"ЗАПОЛНИТЬ|\bTODO\b|\bTBD\b|YYYY-MM-DD", value):
            warnings.append(f"Possible template residue in {filename}; inspect in context.")
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="Check direct package folders in submissions/.")
    args = parser.parse_args()
    if args.all and args.packages:
        parser.error("Choose package paths or --all, not both.")
    if not args.all and not args.packages:
        parser.error("Provide a package path or --all.")
    packages = sorted(p for p in (REPO / "submissions").iterdir() if p.is_dir()) if args.all else args.packages
    if not packages:
        print("No working submissions found. No editorial or delivery checks performed.")
        return 0
    failed = False
    for package in packages:
        errors, warnings = check(package)
        print(f"{'ERROR' if errors else 'STRUCTURE OK'}: {package}")
        for warning in warnings:
            print(f"  NOTE: {warning}")
        for error in errors:
            print(f"  ERROR: {error}")
        failed = failed or bool(errors)
    print("Structure only. Facts, originality, rights, final media and platform delivery require human/editor review.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
