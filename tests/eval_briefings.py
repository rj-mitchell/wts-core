"""For the tests of wts_core.eval: a briefing made up to meet every check, as a fixture and as the events a reader
is sent. Every council, minute and quotation here is invented."""

from __future__ import annotations

from wts_core.eval import Fixture
from wts_core.events import Block, Citation
from wts_core.ports import Document

QUESTION = "What did these councils decide about waste collections?"

DOCUMENTS = (
    Document(1, "Minutes of Northbridge Borough Council, Cabinet, 26 February 2025",
             "https://example.org/northbridge/cabinet/2025-02-26",
             ("The Cabinet agreed that weekly collections of food waste would begin in April 2026.",
              "Cllr. Shah said the old contract had been a poor use of public money.")),
    Document(2, "Minutes of Eastmere District Council, Full Council, 4 March 2025",
             "https://example.org/eastmere/council/2025-03-04",
             ("The Council resolved to keep fortnightly collections of general waste.",)),
)
HEADINGS = ("Waste and recycling service", "Budget and council tax")

# In order: an opener about the records (dropped); American spellings in the model's own words (made British); a
# citation that stands; a claim with no citation, holding a loaded word, a quotation that is in the minutes and one
# that is not; a heading quoted; a citation that stands and one whose words are not in the minutes; and a note
# about the evidence that only the wide form of the rule takes for one.
BLOCKS = (
    Block("Across the records retrieved, two councils took different courses.\n\n"),
    Block("- Northbridge's Cabinet favored a new program: "),
    Block("weekly collections of food waste would begin in April 2026",
          (Citation(0, "The Cabinet agreed that weekly collections of food waste would begin in April 2026."),)),
    Block(". Cllr. Shah slammed the old contract as \"a poor use of public money\" and \"a complete waste of "
          "time\".\n"),
    Block("- Eastmere, under the heading \"Budget and council tax\", kept its collections as they were: "),
    Block("The Council resolved to keep fortnightly collections of general waste.",
          (Citation(1, "The Council resolved to keep fortnightly collections of general waste."),)),
    Block(" It also resolved to scrap them next year.",
          (Citation(1, "The Council resolved to scrap fortnightly collections."),)),
    Block("\n\nThe votes on the amendment to the budget moved by the opposition were not supplied.\n"),
)
CLAIM = ". Cllr. Shah slammed the old contract as \"a poor use of public money\" and \"a complete waste of time\"."
NOTE = "The votes on the amendment to the budget moved by the opposition were not supplied."


def fixture(name: str = "made-up") -> Fixture:
    """The briefing as a fixture with no report yet: a test records one with the checks it starts from."""
    return Fixture(name, QUESTION, DOCUMENTS, BLOCKS, None, HEADINGS)
