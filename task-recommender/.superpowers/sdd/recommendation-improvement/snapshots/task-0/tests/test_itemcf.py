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
