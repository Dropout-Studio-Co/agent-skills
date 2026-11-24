"""Coupon redemption."""
REDEEMED = "SELECT 1 FROM redemptions WHERE code = ? AND user = ?"
INSERT = "INSERT INTO redemptions (code, user) VALUES (?, ?)"


def redeem(conn, code, user):
    """Redeem one coupon for one user; a second redeem for the same user returns False."""
    if conn.execute(REDEEMED, (code, user)).fetchone() is not None:
        return False
    conn.execute(INSERT, (code, user))
    conn.commit()
    return True
