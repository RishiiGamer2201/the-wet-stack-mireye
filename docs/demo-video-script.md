# Two-minute demo script

**320 spoken words. 2:08 at a normal pace, 1:56 brisk.**

Every claim below was verified against the running frontend and API on
2026-08-24, not taken from the README. The measured figures are in the appendix.

**On covering "every feature":** the app has about twenty distinct panels. At two
minutes that is six seconds each, which is a list, not a demo. So this script
*narrates* one thread through the product and *shows* the rest passing under the
cursor. The appendix marks which features are spoken and which are only seen, so
you can swap them if you disagree with the choice.

---

## 0:00 - 0:18 · The problem (46 words)

> A data center gets decided twice. When you choose the site, and again whenever
> equipment gets substituted during construction.
>
> Both depend on physical data. And when part of that data is missing, it is
> very easy to make an assumption without noticing. A blank scores as zero. A
> nearby measurement gets used because it is close enough.

**Screen:** Before construction, ranking table with all nine sites visible.
Cursor still.

---

## 0:18 - 0:42 · Site intelligence (60 words)

> Site Intelligence scores every candidate on thirty physical parameters from
> Mireye, across eight dimensions.
>
> This is not a black box. Every metric shows its value, how it was normalised,
> and the evidence behind it. Change the weight of any dimension and the backend
> re-scores against the same evidence, so you can see what your priorities
> actually cost you.

**Screen:** expand Cascade Flats, scroll the eight dimensions, then drag the
Water weight slider and let the ranking reorder. Open the evidence drawer on one
metric.

*Shown, not narrated: site map, AI Site Scout, manual value override, the
investigation timeline.*

---

## 0:42 - 1:04 · The rule (56 words)

> The important part is what happens when evidence is missing or only nearly
> right.
>
> Mireye publishes a design wet-bulb temperature. Our model needs dry-bulb. Both
> are Celsius, so nothing would break if we swapped them. The score would just be
> wrong. So it is stored as contextual evidence: visible, cited, and unable to
> fill that field or close its gap.

**Screen:** the wet-bulb row with its proxy label, then the gap panel showing
two hundred open gaps, nine of them blocking, each with a next action.

**Hold this one.** It is the whole pitch.

---

## 1:04 - 1:30 · Change intelligence (62 words)

> Second workflow. A chiller substitution.
>
> Nine gates run before any comparison is allowed. Then fifteen unit-checked
> deltas, calculated in Python, not by the model. Design margins, cost and
> schedule impact, and a full decision lineage for why anything was flagged.
>
> Ask it across all three substitutions and it says needs information, and names
> exactly which facility capacities it does not have.

**Screen:** CH-01 change, gates passing, the deltas table, then scroll through
margins and cost. Finish on cascade analysis showing NEEDS INFORMATION with the
named missing capacities.

*Shown, not narrated: the impact graph, thirty nodes and thirty-nine edges.*

---

## 1:30 - 1:48 · Knowledge and recommendation (48 words)

> Upload a submittal and it is parsed, indexed and searchable immediately. If the
> page is a scan, OCR reads it, at half confidence, flagged for a human.
>
> And describe what you need in plain English. It extracts the physics
> constraints and ranks real catalog equipment against them.

**Screen:** drag `Aurora-DC1-Scanned-Field-Markup-SYNTHETIC.pdf` into the upload
area, show the OCR badge appear. Then the recommendation studio: type the chiller
requirement, show the constraints and the ranked candidates.

*Shown, not narrated: the MCP tool registry, the knowledge agent chat, the
EPC advisor.*

---

## 1:48 - 2:00 · Close (36 words)

> Over three thousand evidence records, live from Mireye and five public
> datasets. Two hundred and seventy-seven tests.
>
> When an engineering decision gets made, you should see the evidence and the
> assumptions behind it, not just the answer.

**Screen:** evidence panel with citations visible. Hold, then cut.

---

## Appendix: verified against the running system

Measured on 2026-08-24 by calling every endpoint the frontend calls.

| Claim in the script | Measured |
|---|---|
| thirty physical parameters | 30 fields |
| eight dimensions | 8, 30 metrics on the leader |
| nine sites | 9, all with coordinates |
| two hundred open gaps, nine blocking | 200 open, 9 blocking |
| contextual evidence exists | 268 proxy records, against 2,410 exact |
| nine gates | 9 checks returned |
| fifteen deltas | 15 returned |
| cascade says needs information | `NEEDS_INFORMATION`, headroom `null`, capacities named |
| impact graph | 30 nodes, 39 edges |
| ranks real catalog equipment | 4 candidates, top: York YZ Magnetic Bearing |
| three thousand evidence records | 3,296 |
| 277 tests | 277 passed, 4 skipped |

**Two things to know before you record.**

The demo database has **four documents and none of them are OCR'd**, because it
was seeded before OCR existed. The OCR badge only appears if you upload the
scanned markup live. That upload is in the script for exactly this reason.

The seeded project has **three change cases, not five**. GEN-01 and UPS-1 only
appear in a freshly seeded database. If you want all five, hit *Clear Data* and
let it re-seed before recording.

---

## Delivery notes

**Say "missing", not "null" or "gap".** The judges are Mireye's team.

**The wet-bulb shot is the pitch.** Every other demo will show a full dashboard.
Yours shows a system that declined to fill one in, and says why. Give it its
twenty seconds even if something else has to go.

**Demo in live mode.** CH-01 lands on NEEDS INFORMATION rather than ENGINEER
REVIEW, because real evidence has real gaps. Less tidy, and it matches the
sentence you just said about missing data.

**Pre-load every tab.** A cold-cache Mireye investigation takes about seven
seconds. Run one before you record so the caches are warm.

**If you run over:** cut the recommendation studio sentence. It is the most
impressive feature and the least central to the argument.

**If you run short:** add *"and none of those numbers come from the language
model. It plans and explains. It never writes a number."*
