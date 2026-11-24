Gate: review
Tier: medium
Triggers: none
Key (sha256 of the diff file): 70f073f5116d8d0c89858e50f0ad12f9c292dca0ea553160e6759909c4224943

## Request (verbatim)
Show each user's average quiz score on their profile page.

## Acceptance criteria (PLAN.md)
- profile_summary(user) returns the user's name, number of quizzes taken and average score.
- The average is rounded to the nearest whole point.
- Unit tests cover the summary for a user with several scores.

## Full diff
--- /dev/null
+++ b/stats.py
@@ -0,0 +1,14 @@
+"""Profile statistics."""
+
+
+def average_score(scores):
+    """Mean of a user's quiz scores, rounded to the nearest whole point."""
+    return round(sum(scores) / len(scores))
+
+
+def profile_summary(user):
+    return {
+        "name": user["name"],
+        "quizzes": len(user["scores"]),
+        "average": average_score(user["scores"]),
+    }
--- /dev/null
+++ b/test_stats.py
@@ -0,0 +1,16 @@
+import unittest
+
+from stats import average_score, profile_summary
+
+
+class StatsTest(unittest.TestCase):
+    def test_average(self):
+        self.assertEqual(average_score([80, 90, 100]), 90)
+
+    def test_summary(self):
+        user = {"name": "Ana", "scores": [70, 80]}
+        self.assertEqual(profile_summary(user), {"name": "Ana", "quizzes": 2, "average": 75})
+
+
+if __name__ == "__main__":
+    unittest.main()
