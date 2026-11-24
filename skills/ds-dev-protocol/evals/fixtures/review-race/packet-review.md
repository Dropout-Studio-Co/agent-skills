Gate: review
Tier: high
Triggers: none
Key (sha256 of the diff file): 439241120a296bd517b51588271ccef43bc951a1727bf7ea8c07ef19f0065973

## Request (verbatim)
Let a user redeem a coupon code once; a second redeem for the same user must be refused.

## Acceptance criteria (PLAN.md)
- redeem(conn, code, user) returns True on the first redemption for that user.
- A later redeem of the same code by the same user returns False.
- Two redemptions of one code by different users both succeed.

## Full diff
--- /dev/null
+++ b/coupons.py
@@ -0,0 +1,12 @@
+"""Coupon redemption."""
+REDEEMED = "SELECT 1 FROM redemptions WHERE code = ? AND user = ?"
+INSERT = "INSERT INTO redemptions (code, user) VALUES (?, ?)"
+
+
+def redeem(conn, code, user):
+    """Redeem one coupon for one user; a second redeem for the same user returns False."""
+    if conn.execute(REDEEMED, (code, user)).fetchone() is not None:
+        return False
+    conn.execute(INSERT, (code, user))
+    conn.commit()
+    return True
--- /dev/null
+++ b/test_coupons.py
@@ -0,0 +1,30 @@
+import sqlite3
+import unittest
+
+from coupons import redeem
+
+
+def make_db():
+    conn = sqlite3.connect(":memory:", check_same_thread=False)
+    conn.execute("CREATE TABLE redemptions (code TEXT, user TEXT)")
+    conn.commit()
+    return conn
+
+
+class CouponTest(unittest.TestCase):
+    def test_first_redeem(self):
+        self.assertTrue(redeem(make_db(), "SAVE10", "ana"))
+
+    def test_second_redeem_refused(self):
+        conn = make_db()
+        self.assertTrue(redeem(conn, "SAVE10", "ana"))
+        self.assertFalse(redeem(conn, "SAVE10", "ana"))
+
+    def test_two_users(self):
+        conn = make_db()
+        self.assertTrue(redeem(conn, "SAVE10", "ana"))
+        self.assertTrue(redeem(conn, "SAVE10", "bo"))
+
+
+if __name__ == "__main__":
+    unittest.main()
