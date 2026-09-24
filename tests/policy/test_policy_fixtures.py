"""Parametrized execution of versioned policy decision fixtures."""

from pathlib import Path

import pytest

from warden.policy.fixtures import load_policy_fixture, run_policy_fixture
from warden.policy.loader import load_policy_bundle

_REPOSITORY_ROOT = Path(__file__).parents[2]
_FIXTURE_ROOT = _REPOSITORY_ROOT / "tests/fixtures/policy"
_BUNDLE_ROOT = _REPOSITORY_ROOT / "tests/fixtures/policy-bundles"
_FIXTURE_PATHS = tuple(sorted(_FIXTURE_ROOT.rglob("*.yaml")))
_MINIMUM_FIXTURE_COUNT = 40


@pytest.mark.parametrize("fixture_path", _FIXTURE_PATHS, ids=lambda path: path.stem)
def test_policy_fixture_has_expected_decision(fixture_path: Path) -> None:
    """Every fixture produces its expected effect, rule, and failed conditions."""
    assert len(_FIXTURE_PATHS) >= _MINIMUM_FIXTURE_COUNT
    bundle_directory = (
        _REPOSITORY_ROOT / "policies"
        if fixture_path.parent == _FIXTURE_ROOT
        else _BUNDLE_ROOT / fixture_path.parent.name
    )
    bundle = load_policy_bundle(bundle_directory)
    fixture = load_policy_fixture(fixture_path)

    result = run_policy_fixture(bundle, fixture)
    assert result.effect == fixture.expect.effect
    assert result.rule_id == fixture.expect.rule
    assert result.failed_condition_ids == fixture.expect.failed_conditions
