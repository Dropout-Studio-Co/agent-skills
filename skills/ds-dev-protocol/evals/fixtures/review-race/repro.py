"""Prove the coupon check-then-act race: two threads redeem the same code for one user."""
import os
import sqlite3
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
import coupons


class Held:
    """Hold the first thread after its SELECT until both threads passed the check."""

    def __init__(self, conn, barrier):
        self.conn = conn
        self.barrier = barrier

    def execute(self, sql, params=()):
        cursor = self.conn.execute(sql, params)
        if sql.lstrip().upper().startswith("SELECT"):
            self.barrier.wait(timeout=10)
        return cursor

    def commit(self):
        self.conn.commit()


def main():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE TABLE redemptions (code TEXT, user TEXT)")
    conn.commit()
    barrier = threading.Barrier(2, timeout=10)
    results = []

    def redeem():
        results.append(coupons.redeem(Held(conn, barrier), "SAVE10", "ana"))

    threads = [threading.Thread(target=redeem) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rows = conn.execute("SELECT COUNT(*) FROM redemptions").fetchone()[0]
    print("returns %s; stored redemptions %d (correct: [True, False] and 1)" % (sorted(results), rows))
    return 0 if rows > 1 and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
