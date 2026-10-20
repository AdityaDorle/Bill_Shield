# BillShield hackathon submission

Success bar: a real user actually sends a message with fewer than 20 words changed.

Name / track: Aditya Dorle / [fill in track]
Public repo: https://github.com/AdityaDorle/Bill_Shield
Live link: [add after deployment]

## Discovery — fill with real observations
- Whose bill / type / date (without identifying information):
- Flagged line and hand calculation:
- Message written / did they send / words changed:
- Ten golden pairs: [collect consented, masked examples]

## Needs
Upload photo/PDF, read lines, correct extraction, record promised price and source,
show maths, clarify charges, select disputed lines, draft/edit, copy/open email,
record actual sending, preserve history.

Replay follow-up and why it chose this interface: [observe and fill]

## System boundary
Browser → FastAPI → Groq (extraction, optional number-free opening/closing).
Code owns decimal maths, verdicts, dates, repeat detection, masking, monetary text,
edit distance and storage. Supabase owns authenticated rows and private files.
Original photo/PDF goes to Groq with consent and is not saved.
A sanitized reconstruction is stored with a link and labeled as a reconstruction.

Unknown charges are unexplained, not proven wrong. Tax arithmetic uses confirmed
rates and bases and does not assess tax law. Missing values remain explicitly unverified.

## Data
Bill → line_items; bill → promises; finding → promise; finding_lines → line_items;
draft_message → finding; **message_lines → line_items**; message_events → draft_message.

Each review has an immutable promise snapshot and finding. Revisions create new reviews.
Each copied/edited/email-opened/sent event is a row with time, masked final text,
and word-level Levenshtein distance from the draft.

Do not retain original uploads, names, account numbers, phone numbers or addresses.
Regex masking is a second layer: users must remove personal details from reviewed fields.
Anonymous history is browser-bound; clearing cookies loses access.

## User testing — not yet performed
| Participant | Real masked bill | Sent? | Words changed | Observed surprise |
|---|---|---|---|---|
| Classmate | | | | |
| Stranger, no guidance | | | | |

Missed charge / confusing step / change made:

The fictional sample in the app is not real-user research.
Tax compounding, multi-currency statements, interest schedules and tariff law are not inferred.
Date checks rely on entered dates, not bank posting evidence. Sending is self-reported.
