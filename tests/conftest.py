import glob, os, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SHOW = next(iter(glob.glob(os.path.join(os.path.dirname(ROOT), "I Married*"))), None)


@pytest.fixture(scope="session")
def eps():
    if not SHOW: pytest.skip("input pack not found next to the repo")
    from promo.parse import parse_file
    return {e.number: e for e in (parse_file(f) for f in sorted(glob.glob(os.path.join(SHOW, "*.txt"))))}
