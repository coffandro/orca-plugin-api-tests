# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "Test: no Gamepad API in web views"
# description = "Manual tests for disabling the Gamepad API in Linux web views (coffandro/OrcaSlicer#1)."
# author = "coffandro"
# version = "1.0.0"
# ///
"""Test plugin for "Disable the Gamepad API in web views on Linux" -- coffandro/OrcaSlicer#1, branch
fix/webview-disable-gamepads.

On Linux, a page that asks for gamepads makes WebKitGTK enumerate HID devices through libmanette, which crashes
OrcaSlicer on some devices. The fix turns WebKitGTK's "Gamepads" feature off in Orca's web views (WebKitGTK 2.42
and newer). This plugin opens such a web view and checks, from the page, whether the Gamepad API is there.
"""
import sys

import orca

TITLE = "Test: no Gamepad API in web views"

PAGE = """
<style>
  body { margin: 0; padding: 14px; font-size: 13px; }
  h3 { margin: 0 0 4px; font-size: 15px; }
  .intro, .expect { color: var(--orca-muted); font-size: 12px; }
  .row { border-top: 1px solid var(--orca-border); padding: 8px 0; }
  .status { font-weight: 600; }
  .pass { color: #2e9d4f; } .fail { color: #d0453b; } .check { color: #c08a1e; }
  pre { white-space: pre-wrap; word-break: break-word; font-size: 12px; margin: 4px 0 0; }
</style>
<h3>__TITLE__</h3>
<p class="intro">Platform: __PLATFORM__. The fix only applies on Linux with WebKitGTK 2.42 or newer; elsewhere the
Gamepad API is expected to stay.</p>

<div class="row"><b>Is the Gamepad API exposed?</b> <span class="status" id="st-exposed"></span>
  <div class="expect">Fixed build on Linux: no <code>navigator.getGamepads</code>. Runs when the window opens.</div>
  <pre id="msg-exposed"></pre></div>

<div class="row"><b>Call navigator.getGamepads()</b> <button type="button" id="call">Run</button>
  <span class="status" id="st-call"></span>
  <div class="expect">This is what crashes an unfixed build on an affected device, so it only runs when you click.
  On the fixed build there is nothing to call. To reproduce the crash on an unfixed build, plug in the device
  that triggers it first.</div>
  <pre id="msg-call"></pre></div>

<div class="row"><b>Listen for a controller for 15 s</b> <button type="button" id="listen">Run</button>
  <span class="status" id="st-listen"></span>
  <div class="expect">Plug in or press a button on a controller. Fixed build: nothing is reported.</div>
  <pre id="msg-listen"></pre></div>

<script>
(function () {
  var linux = __LINUX__;
  function show(id, status, text) {
    var st = document.getElementById("st-" + id);
    st.textContent = { pass: "PASS", fail: "FAIL", check: "CHECK" }[status];
    st.className = "status " + status;
    document.getElementById("msg-" + id).textContent = text;
  }
  var exposed = "getGamepads" in navigator && typeof navigator.getGamepads === "function";
  var ua = "User agent: " + navigator.userAgent;
  if (!linux) show("exposed", "check", (exposed ? "Exposed" : "Not exposed") + ", as expected off Linux (the fix is Linux-only).\\n" + ua);
  else if (!exposed) show("exposed", "pass", "navigator.getGamepads is not there: the Gamepad feature is off.\\n" + ua);
  else show("exposed", "fail", "navigator.getGamepads is there: an unfixed build, or WebKitGTK older than 2.42 " +
            "(the AppleWebKit version below tells which).\\n" + ua);

  document.getElementById("call").onclick = function () {
    if (!("getGamepads" in navigator)) { show("call", linux ? "pass" : "check", "Nothing to call: navigator.getGamepads is not there."); return; }
    try {
      var pads = Array.prototype.filter.call(navigator.getGamepads() || [], Boolean);
      show("call", "check", "Returned " + pads.length + " gamepad(s)" + (pads.length ? ": " + pads.map(function (p) { return p.id; }).join(", ") : "") +
           ". Orca is still running, so this device doesn't trigger the crash.");
    } catch (e) { show("call", "check", "Threw " + e); }
  };

  document.getElementById("listen").onclick = function () {
    var seen = [];
    function on(e) { seen.push(e.type + ": " + (e.gamepad && e.gamepad.id)); }
    window.addEventListener("gamepadconnected", on);
    window.addEventListener("gamepaddisconnected", on);
    show("listen", "check", "Listening for 15 s...");
    setTimeout(function () {
      window.removeEventListener("gamepadconnected", on);
      window.removeEventListener("gamepaddisconnected", on);
      if (seen.length) show("listen", linux ? "fail" : "check", "Saw:\\n" + seen.join("\\n"));
      else show("listen", linux ? "pass" : "check", "No gamepad events in 15 s.");
    }, 15000);
  };
})();
</script>
"""


class OpenTests(orca.script.ScriptPluginCapabilityBase):
    window = None

    def get_name(self):
        return TITLE

    def execute(self):
        if OpenTests.window is not None and OpenTests.window.is_open():
            return orca.ExecutionResult.success(f"{TITLE} is already open.")
        linux = sys.platform.startswith("linux")
        html = (PAGE.replace("__TITLE__", TITLE).replace("__PLATFORM__", sys.platform)
                .replace("__LINUX__", "true" if linux else "false"))
        OpenTests.window = orca.host.ui.create_window(html=html, title=TITLE, width=700, height=520)
        return orca.ExecutionResult.success(f"{TITLE} opened.")


@orca.plugin
class GamepadTestPlugin(orca.base):
    def register_capabilities(self):
        orca.register_capability(OpenTests)
