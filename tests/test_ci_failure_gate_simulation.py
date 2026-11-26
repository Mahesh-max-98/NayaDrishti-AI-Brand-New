"""Temporary, isolated test to verify GitHub CI reports failures correctly.

This file is intended only for the verification pull request and must not be
merged into main. It deliberately fails so the PR check can be observed.
"""
import unittest


class TestCIFailureGateSimulation(unittest.TestCase):
    def test_intentional_failure_is_reported(self):
        self.fail("Intentional CI failure-gate simulation; do not merge this test.")


if __name__ == "__main__":
    unittest.main()
