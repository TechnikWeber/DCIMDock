"""Pick how to reach the iPhone: ifuse on Linux, AFC directly on Windows.

DCIMDOCK_BACKEND=afc tries the Windows way on Linux (needs pymobiledevice3).
"""
import os
import sys

if sys.platform == "win32" or os.environ.get("DCIMDOCK_BACKEND", "").lower() == "afc":
    from . import afc as device
else:
    from . import device

__all__ = ["device"]
