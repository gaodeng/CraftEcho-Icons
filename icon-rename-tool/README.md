# CraftEcho-Icons Name Converter

This tool reads icon items from `drawable.xml`, transliterates Chinese names into pinyin (joined, lowercase), converts English names to lowercase with underscores for whitespace, resolves duplicates with numeric suffixes, renames the corresponding PNG files in `drawable-nodpi`, and updates `drawable.xml` and `appfilter.xml` (both in `res/xml` and `assets`).

## Requirements

Python 3.8+ and `pypinyin`:

```bash
pip install -r requirements.txt
```

## Usage

### Preview changes (Dry Run)
Preview all mappings, collision resolutions, and file updates without altering anything on disk:

```bash
python3 icon-rename-tool/convert.py --dry-run
```

### Apply conversion
Execute file renames and XML updates:

```bash
python3 icon-rename-tool/convert.py
```

### Apply and stage with Git
Execute conversion and immediately stage all modified and renamed files in git:

```bash
python3 icon-rename-tool/convert.py --git-add
```

## Options

- `--dry-run`: Preview all changes without modifying any files.
- `--git-add`: Run `git add -A` on all affected files after conversion.
- `--prefix PREFIX`: Prefix for converted icon names (default: `icon_`).
- `--no-keep-existing`: Force re-conversion of existing custom non-hash names (default preserves them).
- `--no-update-appfilter`: Skip updating `appfilter.xml`.
- `--no-sync-assets`: Skip syncing updates to `app/src/main/assets/`.
- `--repo-root PATH`: Path to project root (auto-detected by default).
