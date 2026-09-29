import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "tests" / "test_deploy.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="нужен bash")
def test_deploy_rollback_exit_codes_and_history() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
