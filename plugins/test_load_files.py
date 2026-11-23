# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Test: Plater.load_files"
# description = "Manual tests for orca.host.Plater.load_files."
# author = "coffandro"
# version = "1.0.0"
# ///
"""Test plugin for orca.host.Plater.load_files(paths) -- branch feat/plugin-load-files.

Covers the PR's manual tests: a model and a project file, each from a page handler (the UI thread, where the
load is queued and the call returns at once) and from a background thread (where the call waits for the load
and raises when nothing was added), plus the argument checks.
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
  .pass { color: #2e9d4f; } .fail { color: #d0453b; } .check { color: #c08a1e; } .running { color: var(--orca-muted); }
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
    st.textContent = { pass: "PASS", fail: "FAIL", check: "CHECK" }[m.status] || m.status;
    st.className = "status " + m.status;
    document.getElementById("msg-" + m.id).textContent = m.message || "";
  });
})();
</script>
"""


class Failed(Exception):
    """A check that didn't hold; its message says what happened instead."""


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

TITLE = "Test: Plater.load_files"
INTRO = ("Adds files to the plate the way a drop on the 3D view does. The test files are written to this plugin's "
         "storage folder: a 20 mm cube (STL), and a copy of the current project (3MF) for the project cases.")

# A 20 mm cube, as 12 outward-facing triangles.
_V = [(0, 0, 0), (20, 0, 0), (20, 20, 0), (0, 20, 0), (0, 0, 20), (20, 0, 20), (20, 20, 20), (0, 20, 20)]
_F = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
      (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]


def write_cube(path):
    lines = ["solid cube"]
    for face in _F:
        lines += ["facet normal 0 0 0", " outer loop", *(f"  vertex {x} {y} {z}" for x, y, z in (_V[i] for i in face)),
                  " endloop", "endfacet"]
    path.write_text("\n".join(lines + ["endsolid cube", ""]), encoding="ascii")
    return path


def plater():
    require(orca.host.Plater, "load_files")
    return orca.host.plater()


def make_window(storage):
    folder = pathlib.Path(storage) / "load_files_test"
    folder.mkdir(parents=True, exist_ok=True)
    cube = lambda: write_cube(folder / "test_cube.stl")

    def project():
        # A real Orca project, so loading it brings up Orca's "open as project / import geometry" question.
        path = folder / "test_project.3mf"
        require(orca.host.Plater, "export_3mf_copy")
        orca.host.plater().export_3mf_copy(str(path))
        return path

    def model_ui():
        result = plater().load_files([str(cube())])
        return check(f"Returned {result!r} at once (queued). A 20 mm cube should appear on the plate, "
                     "and Orca should switch to the Prepare tab's 3D view.")

    def model_bg():
        result = plater().load_files([str(cube())])
        return check(f"Returned {result!r} after the load. A 20 mm cube should be on the plate.")

    def project_ui():
        path = project()
        result = plater().load_files([str(path)])
        return check(f"Returned {result!r} at once. Orca should ask how to open {path.name}. Either answer is fine.")

    def project_bg():
        path = project()
        try:
            result = plater().load_files([str(path)])
        except RuntimeError as exc:
            return check(f"Raised RuntimeError: {exc}\nRight if you cancelled Orca's question; wrong if you chose an option.")
        return check(f"Returned {result!r}. Right if you chose an option in Orca's question; wrong if you cancelled.")

    def path_like():
        result = plater().load_files([cube()])  # a pathlib.Path, not a str
        return check(f"Accepted a pathlib.Path (returned {result!r}). Another cube should appear.")

    def bad_arguments():
        p = plater()
        missing = folder / "does_not_exist.stl"
        text = folder / "notes.txt"
        text.write_text("not a model", encoding="utf-8")
        found = [
            "single str: " + raises(lambda: p.load_files(str(cube())), TypeError),
            "empty list: " + raises(lambda: p.load_files([]), ValueError),
            "missing file: " + raises(lambda: p.load_files([str(missing)]), ValueError, "Not a file"),
            "a .txt file: " + raises(lambda: p.load_files([str(text)]), ValueError, "type the plate accepts"),
        ]
        return "\n".join(found)

    return TestWindow(TITLE, INTRO, [
        Case("api", "The build has Plater.load_files", "Passes on a build of feat/plugin-load-files.",
             lambda: require(orca.host.Plater, "load_files"), auto=True),
        Case("args", "Bad arguments are refused", "A single str is a TypeError; an empty list, a missing file "
             "and a file type the plate doesn't take are ValueErrors. Nothing is added.", bad_arguments, auto=True),
        Case("model_ui", "Model, from the page handler", "Returns at once; the cube appears a moment later.", model_ui),
        Case("model_bg", "Model, from a background thread", "Waits until the cube is on the plate, then returns.",
             model_bg, thread=True),
        Case("project_ui", "Project file, from the page handler", "Returns at once; Orca then asks how to open the project.",
             project_ui),
        Case("project_bg", "Project file, from a background thread", "Waits for Orca's question. Cancelling it "
             "raises RuntimeError; choosing an option returns.", project_bg, thread=True),
        Case("pathlike", "A pathlib.Path is accepted", "Loads like a str path.", path_like),
    ])


register(TITLE, make_window)
