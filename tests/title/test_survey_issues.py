from cre_mcp.title import issue_list as issue_list_module
from cre_mcp.title import survey_review as survey_review_module
from cre_mcp.title.issue_list import attorney_issue_list
from cre_mcp.title.survey_review import survey_vs_title


def test_survey_title_matching_and_unmatched_both_ways():
    result = survey_vs_title(
        [
            {
                "type": "utility",
                "description": "A 10-foot utility easement runs along the east boundary.",
            },
            {
                "type": "encroachment",
                "description": "The building extends 2 feet across the west boundary.",
                "direction": "off-site",
            },
        ],
        [
            {
                "text": "Utility easement, 10 feet wide, along the easterly property line.",
                "citation": {
                    "quote": "Utility easement, 10 feet wide, along the easterly property line.",
                    "locator": "Schedule B-II, item 4",
                },
            },
            {
                "text": "Drainage easement over the north 20 feet.",
                "locator": "Schedule B-II, item 5",
            },
        ],
    )

    assert "error" not in result
    assert len(result["matched"]) == 1
    assert result["matched"][0]["survey_index"] == 0
    assert result["matched"][0]["citations"][1]["locator"] == "Schedule B-II, item 4"
    assert len(result["unmatched_survey"]) == 1
    assert result["unmatched_survey"][0]["severity"] == "high"
    assert result["unmatched_survey"][0]["status"] == "new_issue"
    assert len(result["unmatched_exceptions"]) == 1
    assert result["unmatched_exceptions"][0]["status"] == "not_plotted_ask_surveyor"
    assert "ask the surveyor" in result["unmatched_exceptions"][0]["what_to_ask"].lower()
    assert result["redaction_count"] == 0


def test_matched_high_severity_encroachment_remains_an_issue():
    result = survey_vs_title(
        [
            {
                "type": "encroachment",
                "description": "Building foundation encroachment across west boundary, Document 12345.",
            }
        ],
        ["Encroachment shown by survey across west boundary, Document 12345."],
    )

    assert len(result["matched"]) == 1
    assert result["issues"][0]["issue_code"] == "encroachment_professional_review"
    assert result["issues"][0]["severity"] == "high"
    assert result["issues"][0]["legal_conclusion"] is None


def test_issue_list_deduplicates_and_sorts_by_severity():
    common = {
        "summary": "Access easement crosses the proposed building pad",
        "dedupe_key": "access easement building pad",
        "citation": {
            "quote": "Access easement crosses the proposed building pad.",
            "locator": "Schedule B-II, item 8",
        },
        "who": ["title company", "counsel"],
        "what_to_ask": "Ask whether the easement can be relocated or otherwise addressed.",
        "deal_impact_if_unresolved": "The intended building footprint may be affected.",
    }
    result = attorney_issue_list(
        "DEAL-7",
        {"issues": [{**common, "severity": "high"}]},
        {
            "issues": [
                {
                    "summary": "Recorded lis pendens remains active",
                    "severity": "fatal",
                    "citation": {
                        "quote": "Notice of Lis Pendens, status active.",
                        "locator": "encumbrances.records[0]",
                    },
                }
            ]
        },
        None,
        {
            "issues": [
                {
                    **common,
                    "severity": "fatal",
                    "citation": {
                        "quote": "Access easement traverses proposed building pad.",
                        "locator": "recorded_burdens.items[0].text",
                    },
                }
            ]
        },
        None,
    )

    assert result["issue_count"] == 2
    assert [issue["severity"] for issue in result["issues"]] == ["fatal", "fatal"]
    access = next(issue for issue in result["issues"] if issue["dedupe_key"])
    assert access["sources"] == ["title_commitment", "recorded_burdens"]
    assert len(access["citations"]) == 2
    for issue in result["issues"]:
        assert issue["who"]
        assert issue["what_to_ask"]
        assert issue["deal_impact_if_unresolved"]
        assert issue["legal_conclusion"] is None


def test_issue_list_preserves_cross_module_evidence_shapes():
    result = attorney_issue_list(
        title_commitment={
            "requirements": [
                {
                    "quote": "Release the deed of trust before policy issuance.",
                    "locator": "Schedule B-I, item 2",
                    "issue_type": "title_requirement",
                }
            ],
            "gap_review": {
                "summary": "Commitment effective-date gap requires confirmation",
                "evidence": [
                    {
                        "quote": "Effective Date: June 1, 2026 at 8:00 a.m.",
                        "locator": "Commitment cover, paragraph 3",
                    }
                ],
            },
            "gap_note": "Generic gap convention without source evidence",
        },
        encumbrances={
            "findings": [
                {
                    "summary": "Mortgage release status is unknown",
                    "issue_type": "release_gap",
                    "evidence": [
                        {
                            "quote": "Status: unknown",
                            "locator": "records[1].status",
                        }
                    ],
                }
            ],
            "resolution_gaps": [
                {
                    "summary": "No payoff arrangement was provided",
                    "evidence": [
                        {
                            "quote": "Payoffs arranged: none",
                            "locator": "closing_context.payoffs_arranged",
                        }
                    ],
                }
            ],
        },
        legal_comparison={
            "conflicts": [
                {
                    "summary": "Deed and survey acreage differ",
                    "severity": "high",
                    "evidence": [
                        {"quote": "10.00 acres", "locator": "sources[0].acreage"},
                        {"quote": "9.75 acres", "locator": "sources[1].acreage"},
                    ],
                }
            ]
        },
    )

    all_citations = [citation for issue in result["issues"] for citation in issue["citations"]]
    assert {citation["locator"] for citation in all_citations} >= {
        "Schedule B-I, item 2",
        "Commitment cover, paragraph 3",
        "records[1].status",
        "closing_context.payoffs_arranged",
        "sources[0].acreage",
        "sources[1].acreage",
    }
    assert not any(issue["summary"] == "Generic gap convention without source evidence" for issue in result["issues"])
    requirement = next(issue for issue in result["issues"] if issue["issue_code"] == "title_requirement")
    assert requirement["citations"][0]["quote"].startswith("Release the deed")


def test_public_functions_contain_unexpected_failures(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(survey_review_module, "_survey_vs_title", fail)
    assert survey_review_module.survey_vs_title([], []) == {
        "error": "survey/title screening failed: synthetic failure"
    }

    monkeypatch.setattr(issue_list_module, "_attorney_issue_list", fail)
    assert issue_list_module.attorney_issue_list() == {
        "error": "issue-list consolidation failed: synthetic failure"
    }


def test_invalid_inputs_return_error_objects():
    assert "error" in survey_vs_title({}, [])
    assert "error" in attorney_issue_list(deal_id=123)


def test_issue_list_keeps_distinct_same_label_matters_and_preserves_requirement_routing():
    result = attorney_issue_list(
        title_commitment={
            "requirements": [
                {
                    "quote": "Buyer shall deliver the survey.",
                    "locator": "Schedule B-I, item 1",
                    "who_must_act": ["buyer/proposed insured", "surveyor"],
                    "typical_cure_note": "Typical cure convention only: deliver the survey.",
                }
            ]
        },
        survey_review={
            "issues": [
                {
                    "summary": "Title exception was not text-matched to a plotted survey matter",
                    "severity": "medium",
                    "citations": [{"quote": "Drainage easement A", "locator": "item 4"}],
                },
                {
                    "summary": "Title exception was not text-matched to a plotted survey matter",
                    "severity": "medium",
                    "citations": [{"quote": "Drainage easement B", "locator": "item 5"}],
                },
            ]
        },
    )

    assert result["issue_count"] == 3
    requirement = next(issue for issue in result["issues"] if "deliver the survey" in issue["summary"])
    assert requirement["who"] == ["buyer/proposed insured", "surveyor"]
    assert requirement["what_to_ask"].startswith("Typical cure convention")
