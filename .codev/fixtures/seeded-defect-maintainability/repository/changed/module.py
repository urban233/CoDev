"""Recently added helper reviewed in this fixture."""


def validate_order(order):
    """Return True if the order has a positive amount and a currency set."""
    if order.get("id") is not None:
        if order.get("amount") is not None:
            if order.get("amount") > 0:
                if order.get("currency") is not None:
                    return True
                return False
            return False
        return False
    return False
