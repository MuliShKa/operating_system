import math
import unittest

from edge.supervisor import RestartBudget


class RestartBudgetTests(unittest.TestCase):
    def test_limits_restarts_to_a_rolling_window(self) -> None:
        budget = RestartBudget(limit=2, window_s=10)

        self.assertTrue(budget.try_restart(1.0))
        self.assertTrue(budget.try_restart(2.0))
        self.assertFalse(budget.try_restart(3.0))
        self.assertTrue(budget.try_restart(11.0))

    def test_rejects_non_finite_restart_time(self) -> None:
        budget = RestartBudget(limit=1, window_s=10)

        with self.assertRaises(ValueError):
            budget.try_restart(math.nan)


if __name__ == "__main__":
    unittest.main()
