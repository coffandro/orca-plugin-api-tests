# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Test: preset.install_printer"
# description = "Manual tests for orca.host.preset.printer_models / install_printer."
# author = "coffandro"
# version = "1.0.0"
# ///
"""Test plugin for orca.host.preset.printer_models() and install_printer(vendor, model, variant) --
branch feat/plugin-install-printer.

Covers the PR's manual tests: installing a model from a vendor that isn't installed, adding a second nozzle of an
installed model, calling it with unsaved preset changes and declining, and checking that Select/Remove printers
shows the result ticked. The models are picked from printer_models() when a case runs.
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

TITLE = "Test: preset.install_printer"
INTRO = ("Adds a printer model to Orca's printer list the way Select/Remove printers does. The install cases change "
         "your printer list: remove what they add afterwards in Select/Remove printers if you don't want it. "
         "Run \"What the install cases will add\" first to see which models they pick.")


def preset():
    require(orca.host.preset, "printer_models", "install_printer")
    return orca.host.preset


def models():
    return preset().printer_models()


def label(row, variant):
    return f"{row['vendor_name']} {row['name']}, {variant} nozzle ({row['vendor']} / {row['model']})"


def pick_new_vendor(rows):
    installed_vendors = {row["vendor"] for row in rows if row["installed_variants"]}
    for row in sorted(rows, key=lambda r: (r["vendor_name"].lower(), r["name"].lower())):
        if row["vendor"] not in installed_vendors and row["variants"]:
            return row, row["variants"][0]
    return None, None


def pick_second_nozzle(rows, skip=()):
    for row in rows:
        missing = [v for v in row["variants"] if v not in row["installed_variants"]]
        if row["installed_variants"] and missing and (row["vendor"], row["model"]) not in skip:
            return row, missing[0]
    return None, None


def installed_now(row, variant):
    for current in models():
        if current["vendor"] == row["vendor"] and current["model"] == row["model"]:
            return variant in current["installed_variants"]
    return False


def make_window(storage):
    def listing():
        rows = models()
        if not rows:
            raise Failed("printer_models() returned no models")
        keys = {"vendor", "vendor_name", "model", "name", "variants", "installed_variants"}
        bad = [row for row in rows if not keys <= set(row)]
        if bad:
            raise Failed(f"{len(bad)} rows lack fields; first: {bad[0]}")
        vendors = {row["vendor"] for row in rows}
        installed = [row for row in rows if row["installed_variants"]]
        return (f"{len(rows)} models from {len(vendors)} vendors; {len(installed)} models have nozzles installed, e.g. "
                + ", ".join(f"{r['vendor_name']} {r['name']} {r['installed_variants']}" for r in installed[:3]))

    def preview():
        rows = models()
        new_row, new_variant = pick_new_vendor(rows)
        second_row, second_variant = pick_second_nozzle(rows)
        return check("Uninstalled vendor: " + (label(new_row, new_variant) if new_row else "none left") +
                     "\nSecond nozzle: " + (label(second_row, second_variant) if second_row else "none found"))

    def bad_arguments():
        p = preset()
        rows = models()
        row = rows[0]
        return "\n".join([
            "unknown vendor: " + raises(lambda: p.install_printer("NoSuchVendor", row["model"], row["variants"][0]), ValueError),
            "unknown model: " + raises(lambda: p.install_printer(row["vendor"], "NoSuchModel", row["variants"][0]), ValueError),
            "unknown nozzle: " + raises(lambda: p.install_printer(row["vendor"], row["model"], "9.99"), ValueError),
        ])

    def already_installed():
        rows = models()
        row = next((r for r in rows if r["installed_variants"]), None)
        if row is None:
            raise Failed("No model has a nozzle installed")
        preset().install_printer(row["vendor"], row["model"], row["installed_variants"][0])
        return check(f"Returned for {label(row, row['installed_variants'][0])}. Right if Orca didn't ask anything "
                     "and the presets weren't reloaded.")

    def install(pick):
        def run():
            row, variant = pick(models())
            if row is None:
                raise Failed("No model left for this case")
            preset().install_printer(row["vendor"], row["model"], variant)
            if not installed_now(row, variant):
                raise Failed(f"Returned, but printer_models() doesn't list {variant} as installed for {label(row, variant)}")
            return check(f"Installed {label(row, variant)}; printer_models() lists it.\nLook: it's in the printer "
                         "dropdown, Select/Remove printers shows it ticked, and its default filaments are selected there.")
        return run

    def declined():
        row, variant = pick_second_nozzle(models())
        if row is None:
            row, variant = pick_new_vendor(models())
        if row is None:
            raise Failed("No model left to try")
        try:
            preset().install_printer(row["vendor"], row["model"], variant)
        except RuntimeError as exc:
            if installed_now(row, variant):
                raise Failed(f"Raised RuntimeError ({exc}) but {label(row, variant)} was installed anyway")
            return f"Raised RuntimeError: {exc}\nNothing was installed."
        return check(f"Returned and installed {label(row, variant)}. Right only if you didn't have unsaved changes "
                     "or chose Keep/Save: to test declining, edit a setting first and pick Cancel.")

    return TestWindow(TITLE, INTRO, [
        Case("api", "The build has printer_models and install_printer", "Passes on a build of feat/plugin-install-printer.",
             lambda: require(orca.host.preset, "printer_models", "install_printer"), auto=True),
        Case("list", "printer_models() lists the shipped models", "Every row has its fields; some are installed.",
             listing, auto=True),
        Case("args", "Unknown vendor, model or nozzle is refused", "ValueError, before any dialog.", bad_arguments, auto=True),
        Case("preview", "What the install cases will add", "Shows the models picked for the two cases below.", preview, auto=True),
        Case("installed", "A model and nozzle already installed", "Returns at once: no question, no preset reload.",
             already_installed),
        Case("new_vendor", "A model from a vendor that isn't installed", "Installs the vendor's profiles and the model.",
             install(pick_new_vendor)),
        Case("second_nozzle", "A second nozzle of an installed model, from a background thread",
             "Waits for the UI thread; the nozzle is added next to the installed one.", install(pick_second_nozzle), thread=True),
        Case("declined", "Unsaved changes, declined", "First change a setting without saving it. Run, then choose "
             "Cancel in Orca's question: RuntimeError, and nothing is installed.", declined),
    ])


register(TITLE, make_window)
