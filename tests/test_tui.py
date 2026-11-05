import threading
import unittest
from unittest.mock import patch

from cloud_vm import tui


class FakeVM:
    def __init__(self, name, status="running", ssh_host=""):
        self.name = name
        self.status = status
        self.ssh_host = ssh_host
        self.image = ""
        self.created_at = ""


class FakeBackend:
    def __init__(self):
        self.vms = [FakeVM("alpha"), FakeVM("beta", "stopped")]
        self.calls = []

    def list_vms(self):
        return self.vms

    def inspect(self, name):
        self.calls.append(("inspect", name))
        return "details"

    def create(self, name, *, authorized=False):
        self.calls.append(("create", name, authorized))
        return "created"

    def bootstrap(self, name, *, authorized=False):
        self.calls.append(("bootstrap", name, authorized))
        return "bootstrapped"

    def apply(self, name, *, authorized=False):
        self.calls.append(("apply", name, authorized))
        return "applied"

    def remove(self, name, *, authorized=False):
        self.calls.append(("remove", name, authorized))
        return "removed"

    def ssh_args(self, name):
        return ["ssh", name]


class TuiTests(unittest.TestCase):
    def app(self, backend):
        app = tui.FleetApp(backend)
        self.addCleanup(app.executor.shutdown, wait=True, cancel_futures=True)
        return app

    def test_mutation_confirmation_freezes_target_and_cancel_never_calls_backend(self):
        backend = FakeBackend()
        app = self.app(backend)
        app.vms = backend.vms
        app.selected = 0
        app.request_mutation("apply")
        app.selected = 1
        app.confirm_mutation(False)
        self.assertEqual(backend.calls, [])

    def test_authorized_mutation_uses_frozen_vm(self):
        backend = FakeBackend()
        app = self.app(backend)
        app.vms = backend.vms
        app.selected = 0
        app.request_mutation("apply")
        app.selected = 1
        app.confirm_mutation(True)
        self.assertEqual(app.pending_operation[0:2], ("apply", "alpha"))

    def test_delete_requires_exact_vm_name(self):
        backend = FakeBackend()
        app = self.app(backend)
        app.vms = backend.vms
        app.request_mutation("remove")
        app.confirm_mutation(True, "beta")
        self.assertEqual(backend.calls, [])
        self.assertIsNone(app.pending_operation)

    def test_render_is_safe_at_small_and_large_sizes(self):
        backend = FakeBackend()
        app = self.app(backend)
        for size in ((4, 12), (12, 40), (40, 120)):
            screen = tui.FakeScreen(*size)
            app.render(screen)
            self.assertTrue(all(row is not None for row in screen.rows))
        self.assertEqual(backend.vms[0].status, "running")
        app.vms = [FakeVM("status-is-raw", "initializing/provider-specific")]
        screen = tui.FakeScreen(20, 100)
        app.render(screen)
        self.assertIn("initializing/provider-specific", "\n".join(screen.rows))

    def test_long_error_and_terminal_characters_never_draw_into_edge(self):
        app = self.app(FakeBackend())
        app.error = True
        app.message = "authentication failed: " + "x" * 300 + " 界\x1b[31m"
        app._set_output(app.message)
        screen = tui.FakeScreen(12, 40)
        app.render(screen)
        self.assertTrue(
            all(
                x + sum(tui._cell_width(c) for c in text) < screen.width
                for _, x, text, _ in screen.draws
            )
        )
        self.assertNotIn("\x1b", "".join(row for row in screen.rows))

    def test_create_refreshes_inventory_without_bootstrap_or_apply(self):
        backend = FakeBackend()
        app = self.app(backend)
        app.pending_confirmation = ("create", "gamma")
        app.confirm_mutation(True)
        for _ in range(100):
            if not app.busy:
                break
            threading.Event().wait(0.01)
            app._poll()
        app._poll()
        self.assertEqual(backend.calls, [("create", "gamma", True)])
        self.assertEqual([vm.name for vm in app.vms], ["alpha", "beta"])

    def test_run_polls_refresh_during_idle_timeout(self):
        backend = FakeBackend()
        app = self.app(backend)
        screen = tui.FakeScreen(14, 60)
        screen.keys = [-1, ord("q")]
        with patch.object(tui.curses, "curs_set"):
            app.run(screen)
        self.assertEqual([vm.name for vm in app.vms], ["alpha", "beta"])
        self.assertIn("Fleet refreshed", app.message)

    def test_missing_ssh_executable_is_reported_without_crashing(self):
        backend = FakeBackend()
        backend.ssh_args = lambda name: (_ for _ in ()).throw(
            FileNotFoundError("ssh not found")
        )
        app = self.app(backend)
        app.vms = backend.vms
        screen = tui.FakeScreen(14, 60)
        screen.keys = [ord("s"), ord("q")]
        with patch.object(tui.curses, "curs_set"):
            app.run(screen)
        self.assertTrue(app.error)
        self.assertEqual(app.message, "ssh not found")

    def test_worker_result_and_failure_are_reported(self):
        backend = FakeBackend()
        app = self.app(backend)
        app._submit("inspect", "alpha", lambda: "inspection output", False)
        for _ in range(100):
            if not app.busy:
                break
            threading.Event().wait(0.01)
            app._poll()
        app._poll()
        self.assertEqual(app.message, "inspection output")

        app._submit(
            "inspect",
            "alpha",
            lambda: (_ for _ in ()).throw(RuntimeError("access denied")),
            False,
        )
        for _ in range(100):
            if not app.busy:
                break
            threading.Event().wait(0.01)
            app._poll()
        app._poll()
        self.assertTrue(app.error)
        self.assertEqual(app.message, "access denied")
        app.render(tui.FakeScreen(12, 40))
        screen = tui.FakeScreen(12, 40)
        app.render(screen)
        self.assertIn("access denied", "\n".join(screen.rows))

    def test_multiline_inspection_output_is_visible_and_scrollable(self):
        app = self.app(FakeBackend())
        app._set_output(
            "first diagnostic line\nsecond diagnostic line\n" + "detail " * 30
        )
        screen = tui.FakeScreen(12, 40)
        app.render(screen)
        self.assertIn("detail", "\n".join(screen.rows))
        app.output_scroll = 100
        app.render(screen)
        self.assertIn("first diagnostic line", "\n".join(screen.rows))

    def test_selected_vm_scrolls_into_view_and_left_column_is_bounded(self):
        backend = FakeBackend()
        backend.vms = [FakeVM(f"very-long-vm-name-{i}" * 3) for i in range(15)]
        app = self.app(backend)
        app.vms = backend.vms
        app.selected = 14
        screen = tui.FakeScreen(14, 50)
        app.render(screen)
        drawn = "\n".join(screen.rows)
        self.assertIn("very-long-vm-name-14", drawn)
        self.assertIn("SELECTED VM", drawn)
        self.assertLessEqual(len(screen.rows[5]), 50)

    def test_dialog_wraps_full_warning_and_escape_cancels(self):
        app = self.app(FakeBackend())
        app.pending_confirmation = ("remove", "alpha")
        screen = tui.FakeScreen(18, 42)
        screen.keys = ["\x1b"]
        result = app._dialog(
            screen,
            "CONFIRM",
            [
                "Delete deactivates Mattermost users by hostname prefix and irreversibly deletes this VM."
            ],
            True,
            "alpha",
        )
        self.assertIsNone(result)
        self.assertIn(
            "Delete deactivates Mattermost users by hostname prefix and irreversibly deletes this VM.",
            " ".join("\n".join(screen.rows).split()),
        )
        self.assertIsNone(app.pending_confirmation)

    def test_tiny_confirmation_is_cancelled_without_drawing_out_of_bounds(self):
        app = self.app(FakeBackend())
        app.pending_confirmation = ("apply", "alpha")
        screen = tui.FakeScreen(4, 12)
        self.assertIsNone(
            app._dialog(screen, "CONFIRM", ["Long warning text"], False, "alpha")
        )
        self.assertIsNone(app.pending_confirmation)

    def test_backspace_redraws_and_clears_confirmation_input(self):
        screen = tui.FakeScreen(8, 30)
        screen.keys = ["a", "b", "c", "\x7f", "\n"]
        self.assertEqual(tui.FleetApp._read_line(screen, 3, 1, 20), "ab")
        self.assertIn("ab", screen.rows[3])
        self.assertNotIn("abc", screen.rows[3])

    def test_refresh_auth_error_is_actionable(self):
        app = self.app(FakeBackend())
        app._submit(
            "refresh",
            None,
            lambda: (_ for _ in ()).throw(RuntimeError("not authorized")),
            False,
        )
        for _ in range(100):
            app._poll()
            if not app.busy:
                break
            threading.Event().wait(0.01)
        self.assertTrue(app.error)
        self.assertIn("credentials and provider access", app.message)
        screen = tui.FakeScreen(12, 60)
        app.render(screen)
        self.assertIn("not authorized", "\n".join(screen.rows))


if __name__ == "__main__":
    unittest.main()
