import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minios.kernel import Kernel      # noqa: E402
from minios.shell import Shell        # noqa: E402


@pytest.fixture
def kernel():
    """A fresh, non-persistent kernel logged in as the default user."""
    return Kernel(statefile=None)


@pytest.fixture
def shell(kernel):
    return Shell(kernel)


def run(shell, line):
    """Execute a line and return (output, exit_code)."""
    return shell.execute_line(line)
