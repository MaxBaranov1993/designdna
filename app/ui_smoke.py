"""Run the maintained browser regression suite against a local DesignDNA server."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8420"
TESTS = [
    "ui_flow_graph_test.py",
    "ui_flow_nodes_test.py",
    "ui_flow_edit_test.py",
    "ui_flow_page_test.py",
    "ui_flow_drag_performance_test.py",
    "ui_editor_ai_first_test.py",
    "ui_contact_form_fields_test.py",
    "ui_editor_colorpicker_test.py",
    "ui_button_select_test.py",
    "ui_p1_drag_test.py",
    "ui_fill_drag_test.py",
    "ui_renderer_frame_test.py",
    "ui_storage_compaction_test.py",
]


def server_ready() -> bool:
    try:
        with urlopen(BASE + "/api/config", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def wait_for_server(process: subprocess.Popen | None) -> None:
    for _ in range(60):
        if server_ready():
            return
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"DesignDNA server exited with {process.returncode}")
        time.sleep(0.5)
    raise RuntimeError("DesignDNA server did not become ready on port 8420")


def stop_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_test(test_name: str) -> int:
    options: dict[str, object] = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "app" / test_name)],
        cwd=ROOT,
        env=os.environ.copy(),
        **options,
    )
    timeout_seconds = 90 if test_name == "ui_editor_colorpicker_test.py" else 150
    try:
        return process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        print(
            f"TIMEOUT: {test_name} did not exit after {timeout_seconds}s; stopping its browser process tree",
            flush=True,
        )
        stop_process_tree(process)
        return 124


def main() -> int:
    server = None
    if not server_ready():
        server = subprocess.Popen(
            [sys.executable, str(ROOT / "app" / "server.py")],
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

    failures: list[tuple[str, int]] = []
    try:
        wait_for_server(server)
        for test_name in TESTS:
            print(f"\n=== {test_name} ===", flush=True)
            returncode = run_test(test_name)
            if returncode:
                failures.append((test_name, returncode))
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)

    if failures:
        print("\nUI smoke failures:")
        for name, code in failures:
            print(f" - {name}: exit {code}")
        return 1
    print(f"\nALL {len(TESTS)} MAINTAINED UI SMOKES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
