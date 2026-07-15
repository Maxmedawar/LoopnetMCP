"""Deterministic title, legal-description, and survey issue screens.

Every result is advisory and routes unresolved document questions to the title
company, CRE counsel, or the surveyor.  Nothing in this package is a legal
opinion or a substitute for review of the source instruments.
"""

from cre_mcp.title.commitment import parse_title_commitment
from cre_mcp.title.easements import assess_recorded_burdens
from cre_mcp.title.issue_list import attorney_issue_list
from cre_mcp.title.legal_compare import compare_legal_descriptions
from cre_mcp.title.liens import screen_encumbrances
from cre_mcp.title.survey_review import survey_vs_title

__all__ = [
    "parse_title_commitment",
    "screen_encumbrances",
    "compare_legal_descriptions",
    "assess_recorded_burdens",
    "survey_vs_title",
    "attorney_issue_list",
]
