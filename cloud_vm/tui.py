"""Curses fleet interface. All remote work runs outside the drawing thread."""

import curses
import subprocess
import textwrap
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar


class FakeScreen:
    """Minimal screen used by headless rendering tests."""

    def __init__(self, height, width):
        self.height, self.width = height, width
        self.rows = [""] * height
        self.keys = []
        self.draws = []

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.rows = [""] * self.height

    def addnstr(self, y, x, text, count, *args):
        if not (0 <= y < self.height and 0 <= x < self.width and count >= 0):
            raise AssertionError(
                f"out-of-bounds draw: {(y, x, count)} on {(self.height, self.width)}"
            )
        text = str(text)[:count]
        cells = sum(_cell_width(char) for char in text)
        if x + cells > self.width - 1:
            raise AssertionError(
                f"draw reaches terminal edge: {(y, x, text)} on {(self.height, self.width)}"
            )
        self.draws.append((y, x, text, count))
        line = self.rows[y].ljust(x)
        self.rows[y] = (line[:x] + text + line[x + len(text) :])[: self.width - 1]

    def timeout(self, milliseconds):
        self.timeout_ms = milliseconds

    def getch(self):
        key = self.keys.pop(0) if self.keys else -1
        if key == -1:
            time.sleep(0.02)
        return key

    def keypad(self, enabled):
        pass

    def get_wch(self):
        return self.keys.pop(0) if self.keys else "\n"

    def refresh(self):
        pass


def _cell_width(char):
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1


def _safe_addnstr(screen, y, x, value, width=None):
    """Draw printable text without reaching the terminal's lower-right cell."""
    h, w = screen.getmaxyx()
    if not (0 <= y < h and 0 <= x < w - 1):
        return
    available = min(w - x - 1, width if width is not None else w - x - 1)
    if available <= 0:
        return
    chars = []
    cells = 0
    for char in str(value):
        char = char if char.isprintable() else " "
        size = _cell_width(char)
        if cells + size > available:
            break
        chars.append(char)
        cells += size
    if chars:
        try:
            screen.addnstr(y, x, "".join(chars), len(chars))
        except curses.error:
            pass


class FleetApp:
    WARNINGS: ClassVar[dict[str, str]] = {
        "create": "Creating a VM may create paid resources.",
        "bootstrap": "Bootstrap runs a mutable root installer and uses sudo.",
        "apply": "Apply changes Home Manager and sudo shell configuration.",
        "remove": "Delete deactivates Mattermost users by hostname prefix and irreversibly deletes this VM.",
    }

    def __init__(self, backend):
        self.backend = backend
        self.vms = []
        self.selected = 0
        self.message = "Loading fleet…"
        self.error = False
        self.pending_confirmation = None
        self.pending_operation = None
        self.busy = False
        self.mutating = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fleet")
        self.future = None
        self.future_action = None
        self.future_target = None
        self.output_lines = []
        self.output_scroll = 0

    def refresh(self):
        self._submit("refresh", None, self.backend.list_vms, False)

    def request_mutation(self, action, name=None):
        if action not in self.WARNINGS or self.busy:
            return
        target = (
            name
            if action == "create"
            else (self.vms[self.selected].name if self.vms else None)
        )
        if action != "create" and target is None:
            return
        self.pending_confirmation = (action, target)

    def confirm_mutation(self, accepted, typed_name=None):
        frozen = self.pending_confirmation
        self.pending_confirmation = None
        if not accepted or frozen is None:
            return
        action, target = frozen
        if action == "remove" and typed_name != target:
            self.message, self.error = (
                "Deletion cancelled: VM name did not match.",
                True,
            )
            return
        if not target:
            self.message, self.error = "Enter a VM name before creating.", True
            return
        self.pending_operation = (action, target)
        if action == "create":

            def create_and_refresh():
                output = self.backend.create(target, authorized=True)
                try:
                    return output, self.backend.list_vms(), None
                except Exception as exc:  # noqa: BLE001 - backend errors are surfaced to the user
                    return output, None, str(exc) or exc.__class__.__name__

            function = create_and_refresh
        else:
            function = lambda: getattr(self.backend, action)(target, authorized=True)
        self._submit(action, target, function, True)

    def _submit(self, action, target, function, mutating):
        if self.busy:
            return
        self.busy, self.mutating = True, mutating
        self.message, self.error = f"{action.title()} in progress…", False
        self.future = self.executor.submit(function)
        self.future_action, self.future_target = action, target

    def _poll(self):
        future = self.future
        if future is None or not future.done():
            return
        action, target = self.future_action, self.future_target
        self.future = None
        try:
            result = future.result()
            if action == "refresh":
                self.vms = list(result)
                self.selected = min(self.selected, max(0, len(self.vms) - 1))
                self.message = f"Fleet refreshed · {len(self.vms)} VM(s)."
            elif action == "create":
                output, inventory, refresh_error = result
                if inventory is not None:
                    self.vms = list(inventory)
                    self.selected = next(
                        (i for i, vm in enumerate(self.vms) if vm.name == target),
                        self.selected,
                    )
                self.message = str(output) or "VM creation completed."
                if refresh_error:
                    self.message += f" Inventory refresh failed: {refresh_error}"
                self._set_output(self.message)
            else:
                self.message = str(result) or f"{action.title()} complete."
                self._set_output(self.message)
            self.error = False
        except Exception as exc:  # noqa: BLE001 - worker errors are surfaced to the user
            self.message = str(exc) or exc.__class__.__name__
            if action == "refresh":
                self.message = f"Fleet refresh failed: {self.message}. Check credentials and provider access if this is an authentication error."
            self.error = True
            self._set_output(self.message)
        finally:
            self.busy = self.mutating = False
            self.future_action = self.future_target = None

    def _set_output(self, value):
        self.output_lines = str(value).splitlines() or [""]
        self.output_scroll = 0

    def render(self, screen):
        h, w = screen.getmaxyx()
        screen.erase()

        def put(y, x, value, width=None):
            _safe_addnstr(screen, y, x, value, width)

        if h < 12 or w < 24:
            put(0, 0, "Terminal too small · resize to at least 24×12")
            screen.refresh()
            return
        put(0, 1, "CLOUD / FLEET")
        put(1, 1, "↑↓ navigate  r refresh  i inspect  n create  b bootstrap  a apply")
        put(2, 1, "s SSH  d delete  ? help  [/] output  q quit")
        split = min(w - 12, max(12, w * 2 // 5))
        put(4, 1, "VIRTUAL MACHINES")
        list_rows = max(1, h - 10)
        first = min(
            max(0, self.selected - list_rows + 1), max(0, len(self.vms) - list_rows)
        )
        for row in range(list_rows):
            idx = first + row
            if idx >= len(self.vms):
                break
            vm = self.vms[idx]
            mark = "›" if idx == self.selected else " "
            put(5 + row, 1, f"{mark} {vm.name}  ·  {vm.status}", split - 3)
        put(4, split, "SELECTED VM")
        if self.vms and self.selected < len(self.vms):
            vm = self.vms[self.selected]
            for n, value in enumerate(
                (
                    f"Name     {vm.name}",
                    f"Status   {vm.status}",
                    f"Host     {vm.ssh_host}",
                    f"Image    {vm.image}",
                    f"Created  {vm.created_at}",
                )
            ):
                put(6 + n, split, value)
        elif not self.vms:
            put(6, split, "No VMs found. Press r to refresh or n to create.")
        output_title = h - 5
        put(
            output_title,
            1,
            "ERROR / OPERATION OUTPUT" if self.error else "OPERATION OUTPUT",
        )
        visible = max(1, h - output_title - 2)
        expanded = [
            part
            for line in self.output_lines
            for part in (
                textwrap.wrap(
                    line, max(1, w - 2), replace_whitespace=False, drop_whitespace=False
                )
                or [""]
            )
        ]
        start = max(0, len(expanded) - visible - self.output_scroll)
        for row, line in enumerate(expanded[start : start + visible]):
            put(output_title + 1 + row, 1, line)
        put(h - 1, 1, self.message)
        screen.refresh()

    def _dialog(self, screen, title, lines, deletion=False, target=""):
        h, w = screen.getmaxyx()
        if h < 6 or w < 24:
            self.message = "Terminal too small to show the full confirmation. Resize; action cancelled."
            self.pending_confirmation = None
            return None
        width = w - 4
        wrapped = [
            part for line in lines for part in (textwrap.wrap(line, width) or [""])
        ]
        prompt = "Type exact VM name to confirm: " if deletion else "Confirm? [y/N] "
        # Keep every warning visible. Never accept a confirmation after clipping.
        if len(wrapped) + 4 > h:
            self.message = "Terminal too small to show the full confirmation. Resize; action cancelled."
            self.pending_confirmation = None
            return None
        screen.erase()
        y = max(0, (h - len(wrapped) - 4) // 2)
        _safe_addnstr(screen, y, 1, title, w - 2)
        for i, line in enumerate(wrapped):
            _safe_addnstr(screen, y + i + 1, 1, line, width)
        prompt_y = y + len(wrapped) + 2
        _safe_addnstr(screen, prompt_y, 1, prompt, w - 2)
        screen.refresh()
        if hasattr(screen, "timeout"):
            screen.timeout(-1)
        try:
            answer = self._read_line(screen, prompt_y + 1, 1, w - 3)
        finally:
            if hasattr(screen, "timeout"):
                screen.timeout(100)
        if answer is None:
            self.pending_confirmation = None
            self.message = "Confirmation cancelled."
            return None
        return answer if deletion else answer.lower() == "y"

    def _confirm(self, screen):
        action, target = self.pending_confirmation
        sentences = [f"You are about to {action} VM {target}.", self.WARNINGS[action]]
        if action == "create":
            sentences[0] = f"You are about to create VM {target}."
            sentences.append(
                "Deployment uses configuration named after this VM when defined; otherwise it uses the shared base configuration."
            )
        elif action == "apply":
            sentences.append(
                f"Deployment uses configuration named {target} when defined; otherwise it uses the shared base configuration."
            )
        result = self._dialog(
            screen, "CONFIRM REMOTE CHANGE", sentences, action == "remove", target
        )
        if self.pending_confirmation is None:
            return
        if result is None:
            self.confirm_mutation(False)
            return
        self.confirm_mutation(
            result == target if action == "remove" else result,
            result if action == "remove" else None,
        )

    def run(self, screen):
        curses.curs_set(0)
        screen.keypad(True)
        screen.timeout(100)
        self.refresh()
        try:
            while True:
                self._poll()
                self.render(screen)
                key = screen.getch()
                if key == -1:
                    continue
                if self.pending_confirmation:
                    self._confirm(screen)
                elif key in (curses.KEY_UP, ord("k")):
                    self.selected = max(0, self.selected - 1)
                elif key in (curses.KEY_DOWN, ord("j")):
                    self.selected = min(max(0, len(self.vms) - 1), self.selected + 1)
                elif key == ord("r"):
                    self.refresh()
                elif key in map(ord, "b a d") and key != ord(" "):
                    self.request_mutation(
                        {ord("b"): "bootstrap", ord("a"): "apply", ord("d"): "remove"}[
                            key
                        ]
                    )
                elif key == ord("n"):
                    name = self._input(screen, "CREATE VM", "Enter new VM name: ")
                    if name:
                        self.request_mutation("create", name)
                elif key == ord("i") and self.vms:
                    name = self.vms[self.selected].name
                    self._submit(
                        "inspect",
                        name,
                        lambda name=name: self.backend.inspect(name),
                        False,
                    )
                elif key == ord("s") and self.vms and not self.busy:
                    try:
                        args = self.backend.ssh_args(self.vms[self.selected].name)
                        curses.endwin()
                        subprocess.run(args, check=False)
                        self.message, self.error = "SSH session ended.", False
                    except Exception as exc:  # noqa: BLE001 - SSH/backend errors are user-facing
                        self.message, self.error = (
                            str(exc) or exc.__class__.__name__,
                            True,
                        )
                    finally:
                        screen.refresh()
                elif key == ord("?"):
                    self.message = "↑↓ select · r refresh · i inspect · n create · b bootstrap · a apply · s SSH · d delete · [/] scroll output · q quit"
                elif key == ord("]"):
                    self.output_scroll = max(0, self.output_scroll - 1)
                elif key == ord("["):
                    self.output_scroll = min(
                        len(self.output_lines) * 100, self.output_scroll + 1
                    )
                elif key == ord("q"):
                    if self.mutating:
                        self.message = "A mutation is still running. Wait for its result before quitting."
                    elif self.busy:
                        self.message = (
                            "An operation is still running. Wait before quitting."
                        )
                    else:
                        return
                if self.pending_confirmation:
                    self._confirm(screen)
        finally:
            self.executor.shutdown(wait=False, cancel_futures=True)

    def _input(self, screen, title, prompt):
        h, w = screen.getmaxyx()
        if h < 6 or w < 24:
            self.message = (
                "Terminal too small for VM name entry. Resize; action cancelled."
            )
            return None
        screen.erase()
        _safe_addnstr(screen, max(0, h // 2 - 1), 1, title, w - 2)
        _safe_addnstr(screen, h // 2, 1, prompt, w - 2)
        screen.refresh()
        screen.timeout(-1)
        try:
            value = self._read_line(screen, h // 2 + 1, 1, w - 3)
        finally:
            screen.timeout(100)
        if value is None:
            self.message = "VM name entry cancelled."
            return None
        return value.strip() or None

    @staticmethod
    def _read_line(screen, y, x, width):
        value = []
        while True:
            key = screen.get_wch()
            if key in ("\x1b", 27):
                return None
            if key == curses.KEY_RESIZE:
                return None
            if key in ("\n", "\r", curses.KEY_ENTER):
                return "".join(value)
            if key in ("\b", "\x7f", curses.KEY_BACKSPACE):
                if value:
                    value.pop()
                    _safe_addnstr(
                        screen,
                        y,
                        x,
                        "".join(value) + " " * max(0, width - len(value)),
                        width,
                    )
                    screen.refresh()
                continue
            if isinstance(key, str) and key.isprintable() and len(value) < width:
                value.append(key)
                _safe_addnstr(screen, y, x, "".join(value), width)
                screen.refresh()


def run(backend):
    """Launch fleet UI using an already-constructed backend."""
    app = FleetApp(backend)
    curses.wrapper(app.run)
