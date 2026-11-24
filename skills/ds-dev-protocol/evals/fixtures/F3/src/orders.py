from pagination import paginate

PAGE_SIZE = 20


def order_history(orders, page=1):
    return {"page": page, "orders": paginate(orders, page, PAGE_SIZE)}
