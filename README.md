# OrcaSlicer plugin API test plugins

One OrcaSlicer plugin per plugin API change, for testing each change by hand in a build of its branch. Each plugin opens a window listing the manual tests its
PR describes, with a **Run** button per test. A result is:

- **PASS** or **FAIL** when the plugin can tell by itself: an error of the expected type was raised, an
  exported 3MF holds G-code, an installed printer is listed.
- **CHECK** when you have to look at Orca, or at a file, to tell: a post-processing script changed the
  exported G-code, the installed printer is ticked in Select/Remove printers. The text says what to look for.
- **SKIP** when a test can't run in Orca's current state, such as an export with the plate not sliced. The
  text says what to set up.

## The plugins

| # | Change | Branch | Plugin |
|---|---|---|---|
| 1 | `orca.host.Plater.export_sliced` | `feat/plugin-export-sliced` | [test_export_sliced.py](plugins/test_export_sliced.py) |
| 2 | `orca.host.preset.printer_models` / `install_printer` | `feat/plugin-install-printer` | [test_install_printer.py](plugins/test_install_printer.py) |

Each plugin's first test checks that the build has the API at all. It fails with "run this plugin on a build of
the PR's branch" on any other build, so you can also run it on a build without the change to see the difference.

## Using them

1. Start a build of the PR's branch.
2. Open the Plugins dialog, install the plugin's `.py` file from disk, and enable it. It's a single file:
   there's nothing to build or install with it.
3. Run it from the Plugins dialog. Its window opens; run the tests from there. Running it again while the
   window is open does nothing.

After you change a plugin, or pull a newer version, `python3 install.py` copies the files in `plugins/` over the
installed ones, keeping their enabled state and permissions. Restart OrcaSlicer afterwards to load them. Name
plugins to update only those (`python3 install.py test_export_sliced`), and use `--data-dir PATH` for a data folder
other than the usual one. A plugin has to be installed once through the Plugins dialog first: the script lists
any that aren't.

The first test that runs on a background thread makes Orca ask for the plugin's **threading** permission:
allow it, or those tests can't start. The plugins write their test files only to their own storage folder,
which needs no permission.

## What each test needs

### 1. `export_sliced` (`test_export_sliced.py`)

Slice the plate before the export tests. **Current printer and scripts** shows what an export will use.

- **G-code, printer with a post-processing script**: pick a printer that isn't Bambu Lab, and add a
  post-processing script (process settings, Others) that changes the file visibly, for example by appending a
  comment line. The result shows the file's first and last lines.
- **G-code with host="OctoPrint"**: a script sees `SLIC3R_PP_HOST=OctoPrint`, and the result is the name to
  upload under.
- **G-code, BBL printer**: select a Bambu Lab printer and slice. The scripts ran while slicing, so the file is
  written as sliced.
- **A script that renames its output**: use a script that writes one line, a new full path, to
  `<the G-code path it was given>.output_name`. The returned path and the file follow the new name.
- **Unsliced plate**: run it with the plate not sliced, or changed since slicing; it must raise `RuntimeError`.
- **Sliced 3MF**, **bad arguments** and **called from a background thread** check themselves.

### 2. `install_printer` (`test_install_printer.py`)

These tests change your printer list; remove what they add afterwards in Select/Remove printers. **What the
install cases will add** shows the models they pick from `printer_models()`.

- **A model from a vendor that isn't installed** installs the vendor's profiles and the model.
- **A second nozzle of an installed model** runs from a background thread.
- **Unsaved changes, declined**: change a setting without saving it first, run the test, and choose Cancel in
  Orca's question. It must raise `RuntimeError` and install nothing.
- Afterwards, open Select/Remove printers: what was installed is ticked there, with its default filaments
  selected.

## Layout

Every plugin is a single, standalone file. They share a small test harness (the window, the Run
buttons and running a test on a thread), repeated in each file between the "Test harness" markers. Change it in
all of them together.
