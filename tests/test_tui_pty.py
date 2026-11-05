import fcntl
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import unittest


@unittest.skipUnless(sys.platform.startswith("linux"), "PTY regression requires Linux")
class TuiPtyTests(unittest.TestCase):
    def test_long_refresh_error_does_not_crash_curses_at_terminal_edge(self):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 14, 40, 0, 0))
        code = """
from cloud_vm.tui import FleetApp
import curses
class Backend:
    def list_vms(self):
        raise RuntimeError('authentication failed: ' + 'x' * 300)
app = FleetApp(Backend())
curses.wrapper(app.run)
"""
        env = dict(os.environ, TERM="xterm")
        process = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            close_fds=True,
        )
        os.close(slave)
        output = bytearray()
        try:
            for attempt in range(50):
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        output.extend(os.read(master, 4096))
                    except OSError:
                        break
                if process.poll() is not None:
                    break
                if attempt >= 5 and attempt % 5 == 0:
                    os.write(master, b"q")
            if process.poll() is None:
                process.kill()
            self.assertEqual(
                process.wait(timeout=2), 0, output.decode(errors="replace")[-1000:]
            )
            self.assertNotIn(b"addnwstr", output)
            self.assertNotIn(b"Traceback", output)
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.wait()


if __name__ == "__main__":
    unittest.main()
