"""
Tests for modules/claude/_session_env.py.

Covered paths:
- is_non_coordinator_session() returns True when PERSONAL_TRAINER_SESSION=1
- is_non_coordinator_session() returns False when no relevant env var is set
- is_non_coordinator_session() returns False when PERSONAL_TRAINER_SESSION is a non-"1" value
"""

import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

_MODULE_PATH = Path(__file__).parent.parent / "_session_env.py"


def load_module():
    """Import _session_env.py as a module."""
    spec = importlib.util.spec_from_file_location("_session_env", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def session_env():
    """Load _session_env module once per test module."""
    return load_module()


# ---------------------------------------------------------------------------
# Tests: is_non_coordinator_session()
# ---------------------------------------------------------------------------

def test_returns_true_when_personal_trainer_session_set(session_env):
    """is_non_coordinator_session() returns True when PERSONAL_TRAINER_SESSION=1."""
    with patch.dict(os.environ, {"PERSONAL_TRAINER_SESSION": "1"}, clear=False):
        assert session_env.is_non_coordinator_session() is True


def test_returns_false_when_no_relevant_env_var(session_env):
    """is_non_coordinator_session() returns False when PERSONAL_TRAINER_SESSION is unset."""
    env_without_pt = {k: v for k, v in os.environ.items() if k != "PERSONAL_TRAINER_SESSION"}
    with patch.dict(os.environ, env_without_pt, clear=True):
        assert session_env.is_non_coordinator_session() is False


def test_returns_false_when_personal_trainer_session_not_one(session_env):
    """is_non_coordinator_session() returns False when PERSONAL_TRAINER_SESSION is not '1'."""
    with patch.dict(os.environ, {"PERSONAL_TRAINER_SESSION": "0"}, clear=False):
        assert session_env.is_non_coordinator_session() is False
