import pytest


@pytest.mark.bloom("PRJ-TC-001")
def test_measures(bud_assert):
    measured = 3
    assert measured == 3
    assert "b" in "abc", "contains b"
    assert measured
    assert measured != 4
    assert measured < 5
    assert measured > 1
    assert "z" not in "abc"
    bud_assert.assertEqual(measured, 3)
    bud_assert.assertIn("b", "abc")
    bud_assert.assertInRange(measured, 1, 5)


def test_fails_a_check():
    values = [1, 2]
    assert values == [1, 3]


def test_soft_failure_goes_on(bud_assert):
    bud_assert.assertEqual(1, 2, "first")
    bud_assert.assertTrue(True, "after")


def test_abort_on_fail_stops(bud_assert):
    bud_assert.assertEqual(1, 2, "stop", abort_on_fail=True)
    bud_assert.assertTrue(True, "never")


def test_raises():
    raise ValueError("bad value")


def test_skipped(bud_assert):
    bud_assert.skipAssert("not measured here")
    pytest.skip("not on this bench")


@pytest.mark.xfail(reason="known issue")
def test_expected_failure():
    assert False


class TestGroup:
    @pytest.mark.bloom("PRJ-002")
    def test_method(self):
        assert 2 > 1


@pytest.fixture
def broken():
    raise RuntimeError("fixture broke")


def test_setup_error(broken):
    pass


def test_values(bud_assert):
    name = "abc"
    count = 0
    items = [1, 2]
    assert name
    bud_assert.assertTrue(name)
    assert items
    bud_assert.assertTrue(items)
    assert not count
    bud_assert.assertTrue(not count)
    assert count <= 1
    bud_assert.assertTrue(count <= 1)


def test_value_fails():
    empty = ""
    assert empty


@pytest.fixture
def checked_after(bud_assert):
    yield
    bud_assert.assertEqual(1, 2, "after")


def test_teardown_check(checked_after):
    pass


@pytest.mark.xfail(reason="soft check expected to fail")
def test_expected_soft_failure(bud_assert):
    bud_assert.assertEqual(1, 2, "soft")


@pytest.mark.xfail(reason="strict soft check", strict=True)
def test_expected_strict_soft_failure(bud_assert):
    bud_assert.assertEqual(1, 2, "strict soft")


@pytest.mark.xfail(reason="aborted check expected to fail", strict=True)
def test_expected_abort(bud_assert):
    bud_assert.assertEqual(1, 2, "abort", abort_on_fail=True)
