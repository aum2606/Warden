"""Parametrized execution of versioned policy decision fixtures."""

from pathlib import Path

import pytest

from warden.policy.fixtures import load_policy_fixture, run_policy_fixture
from warden.policy.loader import load_policy_bundle

_REPOSITORY_ROOT = Path(__file__).parents[2]
_FIXTURE_PATHS = tuple(sorted((_REPOSITORY_ROOT / "tests/fixtures/policy").glob("*.yaml")))
_MINIMUM_FIXTURE_COUNT = 15


@pytest.mark.parametrize("fixture_path", _FIXTURE_PATHS, ids=lambda path: path.stem)
def test_policy_fixture_has_expected_rule_and_condition_failures(fixture_path: Path) -> None:
    """Every fixture matches its named rule and exposes exactly its failed conditions."""
    assert len(_FIXTURE_PATHS) >= _MINIMUM_FIXTURE_COUNT
    bundle = load_policy_bundle(_REPOSITORY_ROOT / "policies")
    fixture = load_policy_fixture(fixture_path)

    result = run_policy_fixture(bundle, fixture)
    failed_conditions = tuple(
        condition.id for condition in result.condition_results if not condition.passed
    )

    assert result.rule_id == fixture.expect.rule
    assert failed_conditions == fixture.expect.failed_conditions
