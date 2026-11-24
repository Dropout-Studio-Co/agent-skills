import sqlite3
import unittest

from coupons import redeem


def make_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE TABLE redemptions (code TEXT, user TEXT)")
    conn.commit()
    return conn


class CouponTest(unittest.TestCase):
    def test_first_redeem(self):
        self.assertTrue(redeem(make_db(), "SAVE10", "ana"))

    def test_second_redeem_refused(self):
        conn = make_db()
        self.assertTrue(redeem(conn, "SAVE10", "ana"))
        self.assertFalse(redeem(conn, "SAVE10", "ana"))

    def test_two_users(self):
        conn = make_db()
        self.assertTrue(redeem(conn, "SAVE10", "ana"))
        self.assertTrue(redeem(conn, "SAVE10", "bo"))


if __name__ == "__main__":
    unittest.main()
