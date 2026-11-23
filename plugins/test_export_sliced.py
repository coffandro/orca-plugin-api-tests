# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Test: Plater.export_sliced"
# description = "Manual tests for orca.host.Plater.export_sliced."
# author = "coffandro"
# version = "1.0.0"
# ///
"""Test plugin for orca.host.Plater.export_sliced(path, host="File") -- branch
feat/plugin-export-sliced.

Covers the PR's manual tests: exporting .gcode for a printer with a post-processing script and for a BBL
printer, exporting .3mf, calling it on an unsliced plate, and the argument and thread checks.
"""
# ── Test harness (the same in every plugin of this repo) ───────────────────────────────────────────────
import json
import threading
import traceback

import orca

PAGE = """
<style>
  body { margin: 0; padding: 14px; font-size: 13px; }
  h3 { margin: 0 0 4px; font-size: 15px; }
  .intro { margin: 0 0 12px; color: var(--orca-muted); font-size: 12px; white-space: pre-wrap; }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 7px 4px; border-top: 1px solid var(--orca-border); vertical-align: top; }
  .expect { color: var(--orca-muted); font-size: 12px; }
  .where { font-size: 11px; color: var(--orca-muted); }
  .status { font-weight: 600; white-space: nowrap; width: 70px; }
  .pass { color: #2e9d4f; } .fail { color: #d0453b; } .check { color: #c08a1e; } .skip, .running { color: var(--orca-muted); }
  .msg { font-size: 12px; white-space: pre-wrap; word-break: break-word; margin-top: 4px; }
</style>
<h3>__TITLE__</h3>
<p class="intro">__INTRO__</p>
<p><button type="button" id="auto">Run the automatic checks</button></p>
<table id="cases"></table>
<script>
(function () {
  var CASES = __CASES__;
  function esc(s) { var d = document.createElement("span"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  document.getElementById("cases").innerHTML = CASES.map(function (c) {
    return '<tr><td><b>' + esc(c.label) + '</b> <span class="where">' + (c.thread ? "background thread" : "UI thread") +
      (c.auto ? ", automatic" : "") + '</span><div class="expect">' + esc(c.expect) + '</div><div class="msg" id="msg-' + c.id +
      '"></div></td><td class="status" id="st-' + c.id + '"></td><td><button type="button" data-id="' + c.id + '">Run</button></td></tr>';
  }).join("");
  function run(id) {
    var st = document.getElementById("st-" + id);
    st.textContent = "running"; st.className = "status running";
    document.getElementById("msg-" + id).textContent = "";
    orca.postMessage({ command: "run", id: id });
  }
  document.querySelectorAll("button[data-id]").forEach(function (b) { b.onclick = function () { run(b.dataset.id); }; });
  document.getElementById("auto").onclick = function () { CASES.filter(function (c) { return c.auto; }).forEach(function (c) { run(c.id); }); };
  orca.onMessage(function (m) {
    if (!m || m.command !== "result") return;
    var st = document.getElementById("st-" + m.id);
    st.textContent = { pass: "PASS", fail: "FAIL", check: "CHECK", skip: "SKIP" }[m.status] || m.status;
    st.className = "status " + m.status;
    document.getElementById("msg-" + m.id).textContent = m.message || "";
  });
})();
</script>
"""


class Failed(Exception):
    """A check that didn't hold; its message says what happened instead."""


class Skip(Exception):
    """The test can't run in Orca's current state (its message says what to set up); not a failure."""


def check(message):
    """A result a person has to confirm by looking at Orca."""
    return ("check", message)


def raises(call, error, contains=""):
    """Run call() and require it to raise `error` (with `contains` in the message)."""
    try:
        call()
    except error as exc:
        if contains and contains not in str(exc):
            raise Failed(f"raised {type(exc).__name__} as expected, but the message was: {exc}")
        return f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - the wrong exception is the finding
        raise Failed(f"expected {error.__name__}, got {type(exc).__name__}: {exc}")
    raise Failed(f"expected {error.__name__}, but the call succeeded")


def require(obj, *names):
    """Fail clearly on a build without the API under test."""
    missing = [name for name in names if not hasattr(obj, name)]
    if missing:
        raise Failed(f"This OrcaSlicer has no {', '.join(missing)}: run this plugin on a build of the PR's branch.")


class Case:
    def __init__(self, id, label, expect, run, auto=False, thread=False):
        self.id, self.label, self.expect, self.run, self.auto, self.thread = id, label, expect, run, auto, thread


class TestWindow:
    """A window listing the cases; Run executes one on the UI thread (the page handler) or on a thread."""

    def __init__(self, title, intro, cases):
        self.title, self.intro, self.cases = title, intro, {case.id: case for case in cases}
        self.window = None

    def is_open(self):
        return self.window is not None and self.window.is_open()

    def open(self):
        cases = [{"id": c.id, "label": c.label, "expect": c.expect, "auto": c.auto, "thread": c.thread}
                 for c in self.cases.values()]
        html = (PAGE.replace("__TITLE__", self.title).replace("__INTRO__", self.intro)
                .replace("__CASES__", json.dumps(cases).replace("<", "\\u003c")))
        self.window = orca.host.ui.create_window(html=html, title=self.title, width=780, height=680,
                                                 on_message=self.on_message, on_close=self.on_close)

    def on_close(self):
        self.window = None

    def on_message(self, message):  # UI thread
        case = self.cases.get((message or {}).get("id"))
        if not case or message.get("command") != "run":
            return
        if case.thread:
            # Starting a thread asks for the plugin's "threading" permission the first time.
            threading.Thread(target=self._run, args=(case,), daemon=True).start()
        else:
            self._run(case)

    def _run(self, case):
        try:
            result = case.run()
            status, text = result if isinstance(result, tuple) else ("pass", "" if result is None else str(result))
        except Failed as exc:
            status, text = "fail", str(exc)
        except Skip as exc:
            status, text = "skip", str(exc)
        except Exception:  # noqa: BLE001 - report anything unexpected
            status, text = "fail", traceback.format_exc(limit=4)
        if self.window is not None:
            self.window.post({"command": "result", "id": case.id, "status": status, "message": text})


def register(title, make_window):
    """Register a Script capability that opens the test window from the Plugins dialog; make_window(storage)
    builds it, given the plugin's storage folder."""

    class OpenTests(orca.script.ScriptPluginCapabilityBase):
        window = None

        def get_name(self):
            return title

        def execute(self):
            if OpenTests.window is not None and OpenTests.window.is_open():
                return orca.ExecutionResult.success(f"{title} is already open.")
            # The plugin's own folder: written to without a permission prompt. Only callable from a callback.
            OpenTests.window = make_window(orca.host.plugin.storage())
            OpenTests.window.open()
            return orca.ExecutionResult.success(f"{title} opened.")

    @orca.plugin
    class TestPlugin(orca.base):
        def register_capabilities(self):
            orca.register_capability(OpenTests)

    return TestPlugin
# ── End of the harness ──────────────────────────────────────────────────────────────────────────────────
import pathlib
import zipfile

TITLE = "Test: Plater.export_sliced"
INTRO = ("Writes the current plate's slice where a plugin can send it on. Slice the plate first (except for the "
         "\"unsliced plate\" case). Files go to this plugin's storage folder; each result shows where.\n"
         "For the post-processing cases, add a script in the process settings (Others > Post-processing "
         "scripts) that changes the file visibly, e.g. a Python script that appends a comment line.")


def plater():
    require(orca.host.Plater, "export_sliced")
    return orca.host.plater()


def head(path, lines=4):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return "".join(next(handle, "") for _ in range(lines)).rstrip()


def tail(path, size=400):
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - size))
        return handle.read().decode("utf-8", "replace").rstrip().splitlines()[-3:]


def make_window(storage):
    folder = pathlib.Path(storage) / "export_sliced_test"
    folder.mkdir(parents=True, exist_ok=True)

    def setup():
        bundle = orca.host.preset_bundle()
        printer = bundle.printers.get_selected_preset_name()
        scripts = bundle.full_config_value("post_process") or "(none)"
        model = bundle.full_config_value("printer_model") or ""
        return check(f"Printer: {printer} ({model or 'no printer_model'})\nPost-processing scripts: {scripts}\n"
                     "Pick the printer and scripts for the case you want before running it.")

    def gcode(host="File", file="plate.gcode"):
        def run():
            target = folder / file
            if host == "File":
                # "File": the result is the final path, which a script may have renamed.
                name = plater().export_sliced(str(target))
                written = pathlib.Path(name)
            else:
                # Another host: the file is written at the path, the result is the name to upload under.
                name = plater().export_sliced(str(target), host)
                written = target
            if not written.is_file():
                raise Failed(f"Returned {name!r}, but there is no file at {written}")
            return check(f"Returned {name!r}; {written} ({written.stat().st_size} bytes).\nFirst lines:\n{head(written)}\n"
                         "Last lines:\n" + "\n".join(tail(written)) +
                         "\nWith a post-processing script, its change should be in the file; on a BBL printer the "
                         "scripts ran while slicing, so the file is the slice as is.")
        return run

    def three_mf():
        target = folder / "plate.3mf"
        result = plater().export_sliced(str(target))
        with zipfile.ZipFile(target) as archive:
            gcodes = [name for name in archive.namelist() if name.endswith(".gcode")]
        if not gcodes:
            raise Failed(f"{target} has no G-code inside")
        return f"Returned {result!r}; {target} ({target.stat().st_size} bytes) holds {', '.join(gcodes)}."

    def unsliced():
        return raises(lambda: plater().export_sliced(str(folder / "unsliced.gcode")), RuntimeError)

    def bad_arguments():
        p = plater()
        return "\n".join([
            "a .txt path: " + raises(lambda: p.export_sliced(str(folder / "plate.txt")), ValueError),
            "a host for .3mf: " + raises(lambda: p.export_sliced(str(folder / "plate.3mf"), "OctoPrint"), ValueError),
        ])

    def from_thread():
        return raises(lambda: plater().export_sliced(str(folder / "thread.gcode")), RuntimeError, "UI thread")

    return TestWindow(TITLE, INTRO, [
        Case("api", "The build has Plater.export_sliced", "Passes on a build of feat/plugin-export-sliced.",
             lambda: require(orca.host.Plater, "export_sliced"), auto=True),
        Case("args", "Bad arguments are refused", "Another extension, and a host with a .3mf path, are ValueErrors.",
             bad_arguments, auto=True),
        Case("thread", "Called from a background thread", "Refused with RuntimeError: it's UI thread only.",
             from_thread, auto=True, thread=True),
        Case("setup", "Current printer and scripts", "Shows what the export cases below will use.", setup, auto=True),
        Case("unsliced", "Unsliced plate", "Run with the plate NOT sliced (or changed since slicing): RuntimeError.",
             unsliced),
        Case("gcode", "G-code, printer with a post-processing script", "A non-BBL printer with a script set: the "
             "script's change is in the file.", gcode()),
        Case("gcode_host", "G-code with host=\"OctoPrint\"", "Scripts run as for an OctoPrint upload: they see "
             "SLIC3R_PP_HOST=OctoPrint, and the result is the name to upload under.", gcode("OctoPrint", "plate_host.gcode")),
        Case("gcode_bbl", "G-code, BBL printer", "Select a Bambu Lab printer and slice: the file is written as "
             "sliced (BBL ran the scripts while slicing).", gcode(file="plate_bbl.gcode")),
        Case("rename", "A script that renames its output", "Use a script that writes one line, a new full path, to "
             "<the G-code path it was given>.output_name: the returned path and the file follow the new name.",
             gcode(file="plate_rename.gcode")),
        Case("3mf", "Sliced 3MF", "A 3MF with the plate's G-code inside, as a print job sends to a Bambu printer.",
             three_mf),
    ])


register(TITLE, make_window)
