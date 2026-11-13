**A second pass over stored output must be at least as strict as the first, and you can't prove that by reading: fuzz it.**

`verify()` judges each block the model wrote; `recheck_flags` judges each saved segment, without the block it came
from. The study found one way that loses a real flag (a short sentence that `verify()` had split off a lead-in). I
fixed that and thought it done. An independent reviewer then fuzzed 150,000 briefings and found the recheck still
cleared a flag in 8,163: a whole line above a lead-in, a split-off sentence ending "?" or "!", one starting "#".
After a second fix it is 17, all dangling lead-ins with no claim in them (13 November 2026, all three AI sites).

What to take from it:
- Have someone with fresh context review any change to a check, and give them the rule it must keep ("never
  weaker"), not your summary of why it is fine.
- A property test is the right guard: rechecking what today's verifier has just written must change nothing.
- Porting a behaviour to a new surface (the recheck onto Where MPs Stand's cached replays) spreads its faults too.
  That port was withdrawn.
- The package stamps each answer with the version of the rules that wrote it and rechecks only older ones
  (MIGRATION 1.4), so the question can't arise.
