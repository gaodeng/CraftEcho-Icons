#!/usr/bin/env python3
"""
Convert icon names in CraftEcho-Icons:
- Reads items from app/src/main/res/xml/drawable.xml
- Converts Chinese characters to pinyin (joined, e.g. shizhong)
- Converts English/alphanumeric characters to lowercase
- Replaces spaces and punctuation with underscores
- Deduplicates collisions by appending _2, _3, etc.
- Renames corresponding PNG files in app/src/main/res/drawable-nodpi/
- Updates app/src/main/res/xml/drawable.xml and app/src/main/res/xml/appfilter.xml
- Keeps app/src/main/assets/drawable.xml and app/src/main/assets/appfilter.xml in sync
"""

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

try:
    from pypinyin import pinyin, Style
except ImportError:
    print("Error: 'pypinyin' library is required.")
    print("Install it with: pip install pypinyin")
    sys.exit(1)


HASH_DRAWABLE_REGEX = re.compile(r"^icon[0-9a-f]{8}(_v\d+)?$")
VALID_ANDROID_ID_REGEX = re.compile(r"^[a-z][a-z0-9_]*$")


def convert_name(name: str, prefix: str = "icon_") -> str:
    """
    Convert an item name to a valid Android drawable identifier:
    - Unescapes XML entities.
    - Chinese characters are transliterated to pinyin (joined without spaces).
    - English and numbers are lowercased.
    - Spaces and punctuation are converted to underscores.
    - Non-alphanumeric/non-ascii symbols are stripped.
    - Prepends prefix (default 'icon_').
    """
    if not name or not name.strip():
        return f"{prefix}unknown"

    clean_name = html.unescape(name)
    py_list = pinyin(clean_name, style=Style.NORMAL, heteronym=False)
    text = ""
    for item in py_list:
        token = item[0]
        # Remove apostrophes (e.g. what's -> whats)
        token = re.sub(r"['’]", "", token)
        # Convert spaces, punctuation and separators into underscores
        token = re.sub(r"[\s\-_\./+:：·—、！!\(\)（）#\?？\t,\，\－\/&@~\[\]【】\"<>]+", "_", token)
        text += token

    text = text.lower()
    # Strip any characters not in [a-z0-9_] (e.g., trademarks, non-latin scripts)
    text = re.sub(r"[^a-z0-9_]", "", text)
    # Collapse multiple consecutive underscores
    text = re.sub(r"_+", "_", text).strip("_")

    if not text:
        text = "unknown"

    full_name = f"{prefix}{text}"
    # Ensure it starts with a letter and is valid Android resource identifier
    if not VALID_ANDROID_ID_REGEX.match(full_name):
        full_name = f"icon_{full_name}"

    return full_name


def parse_drawable_items(drawable_xml_path: Path) -> List[Tuple[str, str]]:
    """
    Parses <item name="..." drawable="..." /> entries in order from drawable.xml.
    Returns list of (name, drawable).
    """
    items = []
    item_regex = re.compile(r'<item\s+[^>]*name="([^"]*)"[^>]*drawable="([^"]*)"|<item\s+[^>]*drawable="([^"]*)"[^>]*name="([^"]*)"')
    with open(drawable_xml_path, "r", encoding="utf-8") as f:
        for line in f:
            m = item_regex.search(line)
            if m:
                if m.group(1) is not None:
                    name = html.unescape(m.group(1))
                    drawable = m.group(2)
                else:
                    drawable = m.group(3)
                    name = html.unescape(m.group(4))
                items.append((name, drawable))
    return items


def build_rename_mapping(
    items: List[Tuple[str, str]],
    existing_pngs: Set[str],
    prefix: str = "icon_",
    keep_existing: bool = True,
) -> Tuple[Dict[str, str], List[Tuple[str, str, str]]]:
    """
    Builds a 1-to-1 mapping from old_drawable -> new_drawable.
    Handles collision resolution by appending _2, _3, etc.
    Returns (mapping, collisions).
    """
    # Reserved names: all non-hash PNGs already in drawable-nodpi (e.g., app-specific icons, backgrounds)
    reserved = set(f for f in existing_pngs if not HASH_DRAWABLE_REGEX.match(f))
    used_names = set(reserved)
    mapping: Dict[str, str] = {}
    collisions: List[Tuple[str, str, str]] = []  # (name, old_drawable, new_drawable)

    # Pass 1: Keep existing non-hash drawables in drawable.xml unchanged if requested
    if keep_existing:
        for name, drawable in items:
            if not HASH_DRAWABLE_REGEX.match(drawable):
                mapping[drawable] = drawable
                used_names.add(drawable)

    # Pass 2: Assign new names to hash drawables (or all items if keep_existing is False)
    for name, drawable in items:
        if drawable in mapping:
            continue
        base_name = convert_name(name, prefix=prefix)
        target_name = base_name
        counter = 2
        is_collision = False
        while target_name in used_names:
            is_collision = True
            target_name = f"{base_name}_{counter}"
            counter += 1
        used_names.add(target_name)
        mapping[drawable] = target_name
        if is_collision:
            collisions.append((name, drawable, target_name))

    return mapping, collisions


def update_xml_file(file_path: Path, mapping: Dict[str, str], dry_run: bool = False) -> int:
    """
    Replaces drawable="OLD" with drawable="NEW" in XML file, preserving formatting,
    comments, attributes, and whitespace.
    Returns the number of replacements made.
    """
    if not file_path.exists():
        print(f"  [Skip] XML file not found: {file_path}")
        return 0

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    replacement_count = 0

    def replacer(match: re.Match) -> str:
        nonlocal replacement_count
        old_val = match.group(1)
        if old_val in mapping and mapping[old_val] != old_val:
            replacement_count += 1
            return f'drawable="{mapping[old_val]}"'
        return match.group(0)

    new_content = re.sub(r'drawable="([^"]+)"', replacer, content)

    if not dry_run and replacement_count > 0:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)

    return replacement_count


def rename_png_files(
    drawable_dir: Path,
    mapping: Dict[str, str],
    dry_run: bool = False,
) -> Tuple[int, List[str], List[Tuple[str, str, str]]]:
    """
    Renames PNG files in drawable_dir based on mapping.
    If a target file already exists on disk (or is claimed by another rename in this run),
    it avoids overwriting by appending _1, _2, etc., logs the event, and updates mapping
    in-place so that subsequent XML updates remain synchronized.

    Returns (number_renamed, missing_files, disk_conflicts).
    """
    renamed_count = 0
    missing = []
    disk_conflicts = []

    # Track all file basenames currently on disk and destinations claimed during this run
    claimed_names = set(f.stem for f in drawable_dir.glob("*.png"))

    for old_name, new_name in list(mapping.items()):
        if old_name == new_name:
            continue
        old_file = drawable_dir / f"{old_name}.png"
        if not old_file.exists():
            missing.append(old_name)
            continue

        target_name = new_name
        target_file = drawable_dir / f"{target_name}.png"

        # If target file exists on disk or was claimed by another operation in this run (and is not old_file itself)
        if (target_file.exists() or target_name in claimed_names) and target_name != old_name:
            alt_counter = 1
            target_name = f"{new_name}_{alt_counter}"
            target_file = drawable_dir / f"{target_name}.png"
            while target_file.exists() or target_name in claimed_names:
                alt_counter += 1
                target_name = f"{new_name}_{alt_counter}"
                target_file = drawable_dir / f"{target_name}.png"

            prefix_str = "[Dry Run] " if dry_run else ""
            print(f"[!] {prefix_str}Target file exists: '{new_name}.png'. Renaming {old_name}.png to '{target_name}.png' instead.")
            mapping[old_name] = target_name
            disk_conflicts.append((old_name, new_name, target_name))

        if old_name in claimed_names:
            claimed_names.remove(old_name)
        claimed_names.add(target_name)

        if not dry_run:
            old_file.rename(target_file)

        renamed_count += 1

    return renamed_count, missing, disk_conflicts


def main():
    parser = argparse.ArgumentParser(
        description="Convert drawable names in CraftEcho-Icons to pinyin/lowercase."
    )
    script_dir = Path(__file__).resolve().parent
    default_root = script_dir.parent if (script_dir.parent / "app").exists() else Path.cwd()

    parser.add_argument(
        "--repo-root",
        type=Path,
        default=default_root,
        help="Repository root directory (default: CraftEcho-Icons root)",
    )
    parser.add_argument(
        "--drawable-xml",
        type=Path,
        default=None,
        help="Path to res/xml/drawable.xml (default: app/src/main/res/xml/drawable.xml)",
    )
    parser.add_argument(
        "--drawable-dir",
        type=Path,
        default=None,
        help="Path to drawable-nodpi directory (default: app/src/main/res/drawable-nodpi)",
    )
    parser.add_argument(
        "--appfilter-xml",
        type=Path,
        default=None,
        help="Path to res/xml/appfilter.xml (default: app/src/main/res/xml/appfilter.xml)",
    )
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=None,
        help="Path to assets directory (default: app/src/main/assets)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="icon_",
        help="Prefix for converted icon names (default: 'icon_')",
    )
    parser.add_argument(
        "--no-keep-existing",
        action="store_true",
        help="Also re-convert existing non-hash icon names instead of preserving them",
    )
    parser.add_argument(
        "--no-sync-assets",
        action="store_true",
        help="Do not synchronize updates to app/src/main/assets/",
    )
    parser.add_argument(
        "--no-update-appfilter",
        action="store_true",
        help="Do not update appfilter.xml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying any files",
    )
    parser.add_argument(
        "--git-add",
        action="store_true",
        help="Run git add on modified and renamed files after conversion",
    )

    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    drawable_xml = (args.drawable_xml or (repo_root / "app/src/main/res/xml/drawable.xml")).resolve()
    drawable_dir = (args.drawable_dir or (repo_root / "app/src/main/res/drawable-nodpi")).resolve()
    appfilter_xml = (args.appfilter_xml or (repo_root / "app/src/main/res/xml/appfilter.xml")).resolve()
    assets_dir = (args.assets_dir or (repo_root / "app/src/main/assets")).resolve()

    print("=" * 60)
    print("CraftEcho-Icons Name Converter")
    print("=" * 60)
    print(f"Repo root:       {repo_root}")
    print(f"drawable.xml:    {drawable_xml}")
    print(f"drawable-nodpi:  {drawable_dir}")
    print(f"appfilter.xml:   {appfilter_xml}")
    print(f"assets dir:      {assets_dir}")
    print(f"Prefix:          {args.prefix!r}")
    print(f"Keep non-hash:   {not args.no_keep_existing}")
    print(f"Update appfilter:{not args.no_update_appfilter}")
    print(f"Sync assets:     {not args.no_sync_assets}")
    print(f"Dry run mode:    {args.dry_run}")
    print("=" * 60)

    if not drawable_xml.exists():
        print(f"Error: drawable.xml not found at {drawable_xml}")
        sys.exit(1)
    if not drawable_dir.exists():
        print(f"Error: drawable-nodpi directory not found at {drawable_dir}")
        sys.exit(1)

    # 1. Parse items
    items = parse_drawable_items(drawable_xml)
    print(f"[*] Found {len(items)} items in {drawable_xml.name}")

    # 2. Get existing PNG files in drawable-nodpi
    existing_pngs = set(f.stem for f in drawable_dir.glob("*.png"))
    print(f"[*] Found {len(existing_pngs)} PNG files in {drawable_dir.name}")

    # 3. Build mapping
    mapping, collisions = build_rename_mapping(
        items=items,
        existing_pngs=existing_pngs,
        prefix=args.prefix,
        keep_existing=not args.no_keep_existing,
    )

    to_rename = {k: v for k, v in mapping.items() if k != v}
    preserved = {k: v for k, v in mapping.items() if k == v}
    print(f"[*] Total mappings: {len(mapping)}")
    print(f"    - Preserved existing: {len(preserved)}")
    print(f"    - To rename:          {len(to_rename)}")

    # Print sample conversions
    print("\n--- Sample Conversions (First 15 items) ---")
    for name, old_d in items[:15]:
        new_d = mapping[old_d]
        status = "(unchanged)" if old_d == new_d else f"-> {new_d}"
        print(f"  {name:25} {old_d:16} {status}")

    # Print collision resolution examples
    if collisions:
        print(f"\n--- Resolved Collisions ({len(collisions)} items with numeric suffixes) ---")
        for name, old_d, new_d in collisions[:12]:
            print(f"  {name:25} {old_d:16} -> {new_d}")
        if len(collisions) > 12:
            print(f"  ... and {len(collisions) - 12} more")

    # 4. Rename PNG files
    print("\n--- Renaming PNG Files ---")
    renamed_count, missing, disk_conflicts = rename_png_files(drawable_dir, mapping, dry_run=args.dry_run)
    action_str = "[Dry Run] Would rename" if args.dry_run else "Successfully renamed"
    print(f"[*] {action_str} {renamed_count} PNG files in {drawable_dir.name}")
    if disk_conflicts:
        print(f"[*] Resolved {len(disk_conflicts)} unexpected on-disk collisions by appending suffix (_1, _2, etc.)")
    if missing:
        print(f"[!] Warning: {len(missing)} drawables referenced in XML were not found in {drawable_dir.name}:")
        for m in missing[:10]:
            print(f"      {m}.png")
        if len(missing) > 10:
            print(f"      ... and {len(missing) - 10} more")

    # 5. Update XML files
    print("\n--- Updating XML Files ---")
    xml_files_to_update = [drawable_xml]

    if not args.no_update_appfilter:
        xml_files_to_update.append(appfilter_xml)

    if not args.no_sync_assets:
        assets_drawable = assets_dir / "drawable.xml"
        xml_files_to_update.append(assets_drawable)
        if not args.no_update_appfilter:
            assets_appfilter = assets_dir / "appfilter.xml"
            xml_files_to_update.append(assets_appfilter)

    for xml_path in xml_files_to_update:
        count = update_xml_file(xml_path, mapping, dry_run=args.dry_run)
        action_str = "[Dry Run] Would update" if args.dry_run else "Updated"
        try:
            rel_path = xml_path.relative_to(repo_root)
        except ValueError:
            rel_path = xml_path
        print(f"[*] {action_str} {count} drawable references in {rel_path}")

    # 6. Optional git add
    if args.git_add and not args.dry_run:
        print("\n--- Running Git Add ---")
        try:
            paths_to_stage = [
                str(drawable_dir),
                str(drawable_xml),
            ]
            if not args.no_update_appfilter:
                paths_to_stage.append(str(appfilter_xml))
            if not args.no_sync_assets:
                paths_to_stage.append(str(assets_dir / "drawable.xml"))
                if not args.no_update_appfilter:
                    paths_to_stage.append(str(assets_dir / "appfilter.xml"))

            subprocess.run(["git", "add", "-A"] + paths_to_stage, cwd=repo_root, check=True)
            print("[*] Staged changes with 'git add'")
        except Exception as e:
            print(f"[!] Git add failed: {e}")

    print("\n" + "=" * 60)
    if args.dry_run:
        print("Dry run completed! No files were modified.")
        print("Run without --dry-run to apply these changes.")
    else:
        print("All operations completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
