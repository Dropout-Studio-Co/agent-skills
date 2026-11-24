import unittest

from stats import average_score, profile_summary


class StatsTest(unittest.TestCase):
    def test_average(self):
        self.assertEqual(average_score([80, 90, 100]), 90)

    def test_summary(self):
        user = {"name": "Ana", "scores": [70, 80]}
        self.assertEqual(profile_summary(user), {"name": "Ana", "quizzes": 2, "average": 75})


if __name__ == "__main__":
    unittest.main()
