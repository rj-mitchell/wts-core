**Judging a saved briefing's flags again must never clear a flag just because the sentence is short.**

`verify()` marks a whole sentence split off a lead-in as a claim however short it is. That knowledge isn't saved
with the briefing, so `recheck_flags` cleared such a claim (60 characters or fewer) when the briefing was shown
again. Fixed in all three AI sites on 13 November 2026. The wider lesson: any second pass over stored output must
be at least as strict as the first, or it weakens a check silently. The package's replay fixtures guard this.
