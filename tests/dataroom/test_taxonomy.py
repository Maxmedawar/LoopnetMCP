"""Deal-type taxonomy coverage and honesty tests."""

import pytest

from cre_mcp.dataroom.taxonomy import DEAL_TYPES, DOC_TAXONOMY, PHASES, get_taxonomy


@pytest.mark.parametrize("deal_type", DEAL_TYPES)
def test_each_taxonomy_has_cre_scale_unique_keys_and_required_fields(deal_type):
    documents = get_taxonomy(deal_type)
    keys = [document["doc_key"] for document in documents]

    assert 25 <= len(documents) <= 40
    assert len(keys) == len(set(keys))
    assert all(document["phase"] in PHASES for document in documents)
    assert all(document["why_it_matters"] for document in documents)
    assert all(document["what_missing_costs"] for document in documents)


@pytest.mark.parametrize("deal_type", DEAL_TYPES)
def test_title_survey_and_cre_real_estoppel_are_explicit(deal_type):
    keys = {document["doc_key"] for document in DOC_TAXONOMY[deal_type]}

    assert "title_commitment" in keys
    assert "alta_survey" in keys
    if deal_type == "land":
        assert "farm_tenant_estoppels" in keys
    else:
        assert "estoppels" in keys


def test_every_conditional_item_has_a_trigger_and_required_items_do_not():
    for documents in DOC_TAXONOMY.values():
        for document in documents:
            if document["requirement"] == "conditional":
                assert document["required"] is False
                assert document["trigger"]
            else:
                assert document["required"] is True
                assert document["trigger"] is None


def test_unknown_deal_type_is_rejected():
    with pytest.raises(ValueError, match="deal_type must be one of"):
        get_taxonomy("hotel")
