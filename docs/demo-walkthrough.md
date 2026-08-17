# Demo walkthrough (~6 minutes)

Start both servers (see the README), open <http://localhost:5173>, and confirm the amber **Demo
mode** banner reads `Mireye: mock · graph: in_memory · vector: hybrid(lexical+local_vector) · store:
sqlite · LLM: deterministic`. That banner is the honesty statement: nothing here is real data.

---

## Part 1 — Before Construction (3 min)

**1. The project.** Header shows *Aurora DC-1 — 48 MW hyperscale campus (synthetic demo)* with five
candidate sites, three documents, the requirement count, the evidence count and the open-gap count.

**2. Run the investigation.** Click **Run investigation**. The agent:

* geocodes anything address-only,
* fetches 24 broad fields for all five candidates,
* scores, ranks and shortlists the top two,
* **re-plans** — deepens with 10 further fields on the shortlist only,
* re-scores, consolidates gaps, decides, and drafts the next actions.

**3. Read the ranking.** Cascade Flats leads at ~92.9/100 (low risk, 100 % coverage); Delta Fields
is last at ~58.3 (high risk). Under *Why this order*:

> Cascade Flats (92.9) ranks above Rio Verde Mesa (72.9). Largest weighted contributions:
> Water +9.3 pts weighted; Hazards & climate +3.7 pts weighted; Power & grid +2.0 pts weighted.

**4. Show the evidence.** Click **View** on any row. The drawer shows every value with source type,
endpoint, retrieval time, observation time, confidence, coordinates, location resolution and an
amber *Synthetic demo* badge. Scroll to a `missing` item — it reads **"no value — not substituted"**.
That is the product thesis in one line.

**5. Show what is missing.** The information-gap panel lists Prairie Junction's unavailable fields
(grid capacity, permit lead time, wetland fraction), each with *why it matters*, the expected source,
the suggested action, and the **Mireye feature request id** that was filed instead of a guess.

**6. What-if — weights.** Drag **Water** down and **Power & grid** up. The backend re-scores against
the same evidence and the blue panel names every rank change. Nothing is recomputed in the browser.

**7. What-if — a corrected value.** In *Evidence detail*, pick a field, type a confirmed value and
click **Apply & re-rank**. The value is stored as `user_confirmed` evidence, the previous record is
kept and marked superseded, and the ranking updates.

**8. Decision and timeline.** Scroll to the decision card, then the activity timeline: the planned
steps with their rationale, the re-planning note ("Broad pass separated the field; deepening only
on Cascade Flats, Rio Verde Mesa"), and every tool event with its latency.

---

## Part 2 — During Construction (3 min)

Switch to the **During construction** tab. Three synthetic change cases are loaded.

### Case A — CH-01 chiller substitution → **ENGINEER REVIEW**

**1. Compare.** The table puts NT-1100 against VX-1150 property by property, including weight basis,
support points and rating conditions.

**2. Confirm a requirement.** In *Extracted project requirements*, the cooling-capacity requirement
shows its page and the sentence it came from, badged *extracted (90 %)*. Type a corrected value and
**Confirm** — it becomes *confirmed* and its evidence flips to `user_confirmed`. Nothing is analysed
on unconfirmed data without saying so.

**3. Run analysis.** Then read the verification gate: eight gates CLOSED, **Site compatibility
TRIGGERED** — the Rio Verde Mesa design dry-bulb of 46 °C exceeds the proposed unit's rated 35 °C, so
the capacity must be re-rated at site conditions. *That* is the two workflows connecting: a site fact
from workflow 1 invalidating an equipment claim in workflow 2.

**4. Read the deltas.** Weight +9.07 % (4,850 → 5,290 kg), max support point +9.09 %, MCA +12.08 %,
refrigerant charge +10.48 %, capacity +0.48 % (CLOSED, inside 2 %). Every one in canonical units,
with the threshold that classified it.

**5. Stale assumptions.** Five of seven project assumptions flip to **STALE**, each naming the
evidence that changed — dunnage, feeder sizing, N+1 redundancy, refrigerant monitoring, crane pick.

**6. Impact graph.** Six impacts across structural, electrical, mechanical, controls and
installation. The graph view lays out `Change → Stale assumption → Discipline → Activity →
Commissioning`; click any node to isolate its dependency path. Note the structural card: *"flags
that structural coordination is required; it does not assess structural adequacy."*

**7. Decision + next action.** `ENGINEER REVIEW`, with a drafted review comment enumerating every
triggered result and an engineer-confirmation request.

### Case B — CH-02 running change → **FIRST-PASS CHECKS CLOSED**

Run it: every gate CLOSED or SKIPPED, every delta inside threshold, **no impacts, no stale
assumptions, an empty impact graph**. The next action is engineer sign-off. The contrast proves the
system is discriminating, not alarmist.

### Case C — PDU-3 substitution → **NEEDS INFORMATION**

The submittal arrived without weight, dimensions or current. Gates go OPEN, deltas go OPEN, and the
**Replan** phase adds a blocked step per open gate rather than assuming a value. The drafted vendor
evidence request names each missing item and asks for the conditions each value is stated at.

---

## Part 3 — Project knowledge (30 s)

The third tab lists the ingested documents and runs hybrid retrieval with page citations. Try
`minimum circuit ampacity` and note the backend label (`hybrid(lexical+local_vector)`), the page
numbers, and that "Ask Mireye" answers are labelled exploratory and excluded from calculations.
Upload your own PDF from the During Construction tab to see extraction, chunking and requirement
proposals run end to end.

---

## The three sentences to close on

1. The agent chose what to investigate — it deepened only on the shortlist, and it added steps for
   exactly what was missing.
2. Every number came from tested Python; the LLM only planned and explained.
3. Nothing was ever filled in with a guess — missing evidence is a tracked gap with an owner, a
   reason and a drafted request.
