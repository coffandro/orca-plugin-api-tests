# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Test: filament.set_slot_colour"
# description = "Manual tests for orca.host.preset.filament.set_slot_colour."
# author = "coffandro"
# version = "1.0.0"
# ///
"""Test plugin for orca.host.preset.filament.set_slot_colour(slot_number, "#RRGGBB") -- branch
feat/plugin-filament-slot-colour.

Covers the PR's manual tests: setting slots 1 and 2 and checking the sidebar swatches, the plate preview colours
and that the preset isn't marked modified, plus the argument checks and a call from a background thread. The
colours are read back from the project, so most cases check themselves.
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
<table id="cases"></table>
<script>
(function () {
  var CASES = __CASES__;
  function esc(s) { var d = document.createElement("span"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  document.getElementById("cases").innerHTML = CASES.map(function (c) {
    return '<tr><td><b>' + esc(c.label) + '</b> <span class="where">' + (c.thread ? "background thread" : "UI thread") +
      '</span><div class="expect">' + esc(c.expect) + '</div><div class="msg" id="msg-' + c.id +
      '"></div></td><td class="status" id="st-' + c.id + '"></td><td><button type="button" data-id="' + c.id + '">Run</button></td></tr>';
  }).join("");
  function run(id) {
    var st = document.getElementById("st-" + id);
    st.textContent = "running"; st.className = "status running";
    document.getElementById("msg-" + id).textContent = "";
    orca.postMessage({ command: "run", id: id });
  }
  document.querySelectorAll("button[data-id]").forEach(function (b) { b.onclick = function () { run(b.dataset.id); }; });
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
    """One test. run() does it; with thread=True it runs on a background thread. prepare(), if given, runs first
    on the UI thread (for setup only the UI thread may do) and its result is passed to run()."""

    def __init__(self, id, label, expect, run, thread=False, prepare=None):
        self.id, self.label, self.expect, self.run, self.thread, self.prepare = id, label, expect, run, thread, prepare


class TestWindow:
    """A window listing the cases; Run executes one on the UI thread (the page handler) or on a thread."""

    def __init__(self, title, intro, cases):
        self.title, self.intro, self.cases = title, intro, {case.id: case for case in cases}
        self.window = None

    def is_open(self):
        return self.window is not None and self.window.is_open()

    def open(self):
        cases = [{"id": c.id, "label": c.label, "expect": c.expect, "thread": c.thread}
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
        try:
            prepared = (case.prepare(),) if case.prepare else ()
        except Exception:  # noqa: BLE001 - a failed setup is reported like a failed test
            self._post(case, "fail", "Setup failed:\n" + traceback.format_exc(limit=4))
            return
        if case.thread:
            # Starting a thread asks for the plugin's "threading" permission the first time.
            threading.Thread(target=self._run, args=(case, prepared), daemon=True).start()
        else:
            self._run(case, prepared)

    def _post(self, case, status, text):
        if self.window is not None:
            self.window.post({"command": "result", "id": case.id, "status": status, "message": text})

    def _run(self, case, prepared=()):
        try:
            result = case.run(*prepared)
            status, text = result if isinstance(result, tuple) else ("pass", "" if result is None else str(result))
        except Failed as exc:
            status, text = "fail", str(exc)
        except Skip as exc:
            status, text = "skip", str(exc)
        except Exception:  # noqa: BLE001 - report anything unexpected
            status, text = "fail", traceback.format_exc(limit=4)
        self._post(case, status, text)


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
import re


TITLE = "Test: filament.set_slot_colour"
INTRO = ("Gives a filament slot one solid colour, as its colour picker does, without changing the slot's preset. "
         "Use a printer with at least two filament slots and an object on the plate. \"Restore\" puts back the "
         "colours the slots had when this window opened.")


def filament():
    require(orca.host.preset.filament, "set_slot_colour")
    return orca.host.preset.filament


def colours():
    raw = orca.host.preset_bundle().full_config_value("filament_colour") or ""
    return [part.strip().strip('"').upper() for part in raw.split(";") if part.strip()]


def need_slots(count):
    """Skip a test that needs more filament slots than the current printer has. UI thread only."""
    slots = len(orca.host.preset_bundle().current_filament_preset_names())
    if slots < count:
        raise Skip(f"This printer has {slots} filament slot{'s' if slots != 1 else ''}. Add filaments in the "
                   f"sidebar (+ next to Filament) until there are {count}, then run this test again.")


def edited_filament_dirty():
    return bool(orca.host.preset_bundle().filaments.get_edited_preset().is_dirty)


def make_window(storage):
    original = colours()

    def set_and_read(slot, colour, expected):
        def run():
            need_slots(slot)
            dirty_before = edited_filament_dirty()
            filament().set_slot_colour(slot, colour)
            now = colours()
            if len(now) < slot or now[slot - 1] != expected:
                raise Failed(f"Slot {slot} reads back as {now[slot - 1] if len(now) >= slot else 'missing'}, not {expected}")
            if edited_filament_dirty() and not dirty_before:
                raise Failed("The edited filament preset is marked modified after the call")
            return check(f"Slot {slot} is {expected} in the project, and the preset isn't marked modified.\n"
                         "Look: the slot's sidebar swatch and the object's colour in the 3D view should match.")
        return run

    def from_thread():
        # The presets are only read on the UI thread, so this case makes the call and leaves the looking to you.
        # Without a second slot the call is refused; its message says how many slots the printer has.
        try:
            filament().set_slot_colour(2, "#AA22CC")
        except IndexError as exc:
            found = re.search(r"has (\d+) filament slot", str(exc))
            if found and int(found.group(1)) < 2:
                raise Skip(f"{exc}. Add a second filament in the sidebar (+ next to Filament), then run this test again.")
            raise
        return check("Returned without an error. Slot 2's swatch and its objects should now be purple (#AA22CC).")

    def bad_arguments():
        f = filament()
        process = orca.host.preset.process
        return "\n".join([
            "\"red\": " + raises(lambda: f.set_slot_colour(1, "red"), ValueError),
            "\"#12345\": " + raises(lambda: f.set_slot_colour(1, "#12345"), ValueError),
            "\"#GGGGGG\": " + raises(lambda: f.set_slot_colour(1, "#GGGGGG"), ValueError),
            "slot 0: " + raises(lambda: f.set_slot_colour(0, "#FF8800"), IndexError),
            "slot 99: " + raises(lambda: f.set_slot_colour(99, "#FF8800"), IndexError),
            "process editor: " + raises(lambda: process.set_slot_colour(1, "#FF8800"), ValueError, "only available on"),
        ])

    def restore():
        f = filament()
        for slot, colour in enumerate(original, 1):
            f.set_slot_colour(slot, colour)
        return f"Restored {', '.join(original) or 'nothing'}."

    return TestWindow(TITLE, INTRO, [
        Case("api", "The build has filament.set_slot_colour", "Passes on a build of feat/plugin-filament-slot-colour.",
             lambda: require(orca.host.preset.filament, "set_slot_colour")),
        Case("args", "Bad arguments are refused", "A value that isn't #RRGGBB and the process editor raise ValueError; "
             "slot 0 and slot 99 raise IndexError. No colour changes.", bad_arguments),
        Case("slot1", "Slot 1 to #FF8800", "Reads back as #FF8800; the swatch and the preview turn orange.",
             set_and_read(1, "#FF8800", "#FF8800")),
        Case("slot2", "Slot 2 to 00AA11 (no #)", "The # is optional: reads back as #00AA11 (green).",
             set_and_read(2, "00AA11", "#00AA11")),
        Case("lower", "Slot 1 to #3366ff (lower case)", "Stored upper case: reads back as #3366FF (blue).",
             set_and_read(1, "#3366ff", "#3366FF")),
        Case("thread", "Slot 2 to #AA22CC from a background thread", "Waits for the UI thread, then slot 2 turns purple.",
             from_thread, thread=True),
        Case("restore", "Restore the original colours", "Puts back the colours from when this window opened.", restore),
    ])


register(TITLE, make_window)
