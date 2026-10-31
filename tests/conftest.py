import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def otekon_result():
    from identification.examples import load_otekon_curves
    from identification.optimizer import preset_otekon, run_identification
    curves = load_otekon_curves()
    return curves, run_identification(curves, preset_otekon())
