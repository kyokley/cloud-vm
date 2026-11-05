import unittest
from unittest import mock

from cloud_vm.__main__ import main


class FleetCliTests(unittest.TestCase):
    @mock.patch("cloud_vm.__main__.FleetBackend")
    def test_create_accepts_optional_name_and_requires_yes(self, backend_class):
        backend = backend_class.return_value
        backend.create.return_value = "provider output\n"

        with mock.patch("sys.stdout"):
            self.assertEqual(main(["create", "--yes"]), 0)
        backend.create.assert_called_once_with(None, authorized=True)

        backend.create.reset_mock()
        with self.assertRaises(SystemExit) as raised:
            main(["create"])
        self.assertEqual(raised.exception.code, 2)
        backend.create.assert_not_called()

    @mock.patch("cloud_vm.__main__.FleetBackend")
    def test_create_with_explicit_name_is_forwarded(self, backend_class):
        backend = backend_class.return_value
        backend.create.return_value = "provider output\n"
        with mock.patch("sys.stdout"):
            self.assertEqual(main(["create", "named-vm", "--yes"]), 0)
        backend.create.assert_called_once_with("named-vm", authorized=True)


if __name__ == "__main__":
    unittest.main()
