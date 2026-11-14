from app.models.itemcf import ItemCF


def test_cold_start_is_zero():
    cf = ItemCF([])
    assert cf.score("w1", "t1") == 0.0


def test_similar_tasks_give_positive_score():
    cf = ItemCF([("w1", "t1", 1.0), ("w1", "t2", 1.0)])
    assert cf.score("w1", "t2") > 0.0


def test_normalize_bounds():
    cf = ItemCF([])
    assert cf.normalize({}) == {}
    assert cf.normalize({("w1", "t1"): 0.0}) == {("w1", "t1"): 0.0}


from app.models.itemcf import ItemCF


def test_normalize_divides_by_max():
    cf = ItemCF([])
    result = cf.normalize({("w1", "t1"): 0.2, ("w2", "t2"): 0.4})
    assert result[("w1", "t1")] == 0.5
    assert result[("w2", "t2")] == 1.0


def test_normalize_all_zero_returns_zero():
    cf = ItemCF([])
    result = cf.normalize({("w1", "t1"): 0.0, ("w2", "t2"): 0.0})
    assert result == {("w1", "t1"): 0.0, ("w2", "t2"): 0.0}
