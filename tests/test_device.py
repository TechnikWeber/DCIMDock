"""Parsing the output of libimobiledevice's tools."""
import unittest

from dcimdock import device


class TestDevice(unittest.TestCase):
    def test_ids(self):
        out = "00008110-001A2B3C4D5E801E\n00008110-001A2B3C4D5E801E\n"
        self.assertEqual(device.parse_ids(out), ["00008110-001A2B3C4D5E801E"])
        self.assertEqual(device.parse_ids("ERROR: Unable to retrieve device list!\n"), [])
        self.assertEqual(device.parse_ids("0123456789abcdef0123456789abcdef01234567 (USB)\n"),
                         ["0123456789abcdef0123456789abcdef01234567"])

    def test_info(self):
        out = "DeviceName: Philipps iPhone\nProductType: iPhone15,2\nProductVersion: 26.1\n"
        d = device.parse_info(out)
        self.assertEqual(d["DeviceName"], "Philipps iPhone")
        self.assertEqual(d["ProductVersion"], "26.1")

    def test_pair_messages(self):
        c = device.classify_pair
        self.assertEqual(c(0, "SUCCESS: Paired with device 0000"), "ready")
        self.assertEqual(c(0, "SUCCESS: Validated pairing with device 0000"), "ready")
        self.assertEqual(c(1, "ERROR: Could not validate with device 0000 because a passcode is set. "
                              "Please enter the passcode on the device and retry."), "locked")
        self.assertEqual(c(1, "ERROR: Please accept the trust dialog on the screen of device 0000, "
                              "then attempt to pair again."), "trust")
        self.assertEqual(c(1, "ERROR: Device 0000 said that the user denied the trust dialog."), "denied")
        self.assertEqual(c(1, "ERROR: No device found."), "gone")
        self.assertEqual(c(1, "something else"), "error")

    def test_mounts(self):
        text = "dcimdock /run/user/1000/dcimdock/ABC fuse.ifuse ro 0 0\n" \
               "/dev/sda1 /media/my\\040disk ext4 rw 0 0\n"
        self.assertEqual(device.parse_mounts(text), ["/run/user/1000/dcimdock/ABC", "/media/my disk"])

    def test_install_command(self):
        self.assertIn("dnf", device.install_command({"ID": "fedora"}))
        self.assertIn("apt", device.install_command({"ID": "linuxmint", "ID_LIKE": "ubuntu debian"}))
        self.assertIn("pacman", device.install_command({"ID": "endeavouros", "ID_LIKE": "arch"}))
        self.assertIn("zypper", device.install_command({"ID": "opensuse-tumbleweed", "ID_LIKE": "opensuse suse"}))


if __name__ == "__main__":
    unittest.main()
