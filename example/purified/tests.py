from calc import add, subtract, multiply, divide

def test_add():
    a = 2
    b = 3
    result = add(a, b)
    assert result == 5

def test_add_zero_and_negative():
    a = -1
    b = 1
    result = add(a, b)
    assert result == 0

def test_add_zeros():
    a = 0
    b = 0
    result = add(a, b)
    assert result == 0

def test_sub():
    a = 5
    b = 3
    result = subtract(a, b)
    assert result == 2

def test_sub_zero():
    a = 0
    b = 0
    result = subtract(a, b)
    assert result == 0

def test_sub_negatives():
    a = -1
    b = -1
    result = subtract(a, b)
    assert result == 0

def test_mul():
    a = 2
    b = 2
    result = multiply(a, b)
    assert result == 4

def test_mul_with_zero():
    a = 0
    b = 5
    result = multiply(a, b)
    assert result == 0

def test_div():
    a = 6
    b = 3
    result = divide(a, b)
    assert result == 2

def test_divide_by_zero():
    a = 5
    b = 0
    try:
        divide(a, b)
    except ValueError as e:
        assert str(e) == 'Cannot divide by zero'

def disabled_test_calculator():
    x = 2
    y = 3
    sum_result = add(x, y)
    assert sum_result == 5
    prod_result = multiply(x, y)
    assert prod_result == 6