from cart import total


def test_total_multiplies_by_quantity():
    assert total([{"price": 3, "qty": 2}]) == 6
