from calc import add, subtract, multiply, divide

def test_calculator():
    x = 2
    y = 3
    prod_result = multiply(x, y)
    assert prod_result == 6