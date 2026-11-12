from buyer_agent.shopper import match_template, terms_template

CATALOG = [
    {"sku": "eth-1kg", "name": "Ethiopian Yirgacheffe 1 kg"},
    {"sku": "col-250", "name": "Colombian Huila 250 g"},
]


def test_match_template_picks_best_overlap_and_quantity():
    i = match_template("order 2 bags of the Ethiopian", CATALOG)
    assert (i.sku, i.quantity) == ("eth-1kg", 2)
    assert match_template("a pony", CATALOG) is None


def test_terms_template_periods_and_amounts():
    assert terms_template("$12.50 daily on tea").model_dump() == {
        "budget_minor": 1250, "period": "DAY", "per_purchase_cap_minor": None, "categories": ["tea"]}
    assert terms_template("200 dollars a month for brewing supplies").period == "MONTH"
    assert terms_template("no number here") is None
