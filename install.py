"""Update the installed test plugins in OrcaSlicer with the versions in plugins/.

    python3 install.py                    # every plugin, into OrcaSlicer's default data folder
    python3 install.py test_load_files    # only the plugins named (with or without .py)
    python3 install.py --data-dir PATH    # into the data folder at PATH

Orca only loads a plugin installed through its Plugins dialog, which also records it as enabled. So install each
plugin once from there ("install from file"), then this copies a newer version over the installed one, the way
the dialog lays it out: orca_plugins/<file name>/<file name>. Restart OrcaSlicer to load it.
"""

import argparse
import os
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLUGINS = ROOT / "plugins"


def default_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ["APPDATA"]) / "OrcaSlicer"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "OrcaSlicer"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "OrcaSlicer"


def install(plugin: Path, data_dir: Path) -> Path | None:
    folder = data_dir / "orca_plugins" / plugin.name
    if not folder.is_dir():
        return None
    shutil.copyfile(plugin, folder / plugin.name)
    shutil.rmtree(folder / "__pycache__", ignore_errors=True)
    return folder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plugins", nargs="*", metavar="PLUGIN", help="Plugins to update (default: all)")
    parser.add_argument("--data-dir", type=Path, help="OrcaSlicer's data folder (default: the usual one for this OS)")
    args = parser.parse_args()

    available = {path.stem: path for path in sorted(PLUGINS.glob("test_*.py"))}
    names = [name.removesuffix(".py") for name in args.plugins] or list(available)
    unknown = [name for name in names if name not in available]
    if unknown:
        sys.exit(f"No such plugin: {', '.join(unknown)} (there are: {', '.join(available)})")

    data_dir = args.data_dir or default_data_dir()
    missing = []
    for name in names:
        folder = install(available[name], data_dir)
        if folder:
            print(f"Updated {folder}")
        else:
            missing.append(available[name])
    if missing:
        print(f"\nNot installed yet in {data_dir}: install these once through OrcaSlicer's Plugins dialog, then run this again:")
        for plugin in missing:
            print(f"  {plugin}")
    if len(missing) < len(names):
        print("\nRestart OrcaSlicer to load the updated plugins.")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
