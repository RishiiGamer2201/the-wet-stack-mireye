# Two-minute video script

**329 words. About 132 seconds spoken at a normal pace, 120 at a brisk one.**

The draft this came from ran 496 words, which is 3:18 spoken and 3:00 even
rushed, against a hard 2:00 cap. Same voice and same structure, cut to fit.

What was cut and why is at the bottom, so you can put something back if you would
rather trade it for something else.

One correction carried in: the chiller delta is **440 kg**, not 450. The seeded
case goes 4,850 kg to 5,290 kg. Say a number a judge can check, or say "over
four hundred kilograms".

---

## The Problem

> A data center gets decided twice. When you choose the site, and again whenever
> equipment gets changed during construction.
>
> Both decisions depend on physical data. And when some of it is missing, it is
> very easy to make assumptions without realising it. A missing value gets
> treated like zero. A nearby measurement gets used because it is close enough.
>
> Wet Stack exists to make sure that doesn't happen.

*On screen: the ranked site table, still. Don't click yet.*

---

## What We Built

> An intelligence layer on top of Mireye. Site Intelligence evaluates a site
> before construction; Change Intelligence checks equipment substitutions during
> it. Both show you where the answer came from, not just the answer.

*On screen: open the evidence drawer so citations are visible.*

---

## How It Works

> Our main design decision was to keep the AI separate from the engineering
> calculations. The agents decide what to investigate, find the evidence, and
> explain the result. Every calculation and unit conversion happens in
> deterministic Python.
>
> So when I swap this chiller and the new unit is four hundred and forty
> kilograms heavier, Python calculates that delta against the structural margin.
> The agent explains whether it needs engineering review.

*On screen: the CH-01 change, then the deltas table.*

---

## Evidence Integrity

> The other half is missing data. If something hasn't been measured, we don't
> fill it in. We mark it missing and give a next action, like commissioning a
> geotechnical survey.
>
> We also check that evidence is relevant. Two values sharing a unit doesn't make
> them interchangeable. Wet-bulb and dry-bulb are both in Celsius, but they are
> different things, so the system won't quietly substitute one for the other.

*On screen: the wet-bulb proxy label and its note. Hold this one. It is the
single most important shot in the video.*

---

## What We've Actually Built

> This runs on real data. Over two thousand live Mireye records, hundreds of
> tests passing, five public datasets connected.
>
> In Virginia it found very high dissolved solids in the groundwater, which
> changes the cooling design. In Arizona, very high wildfire risk, and it
> corrected a classification error we had missed.

*On screen: Harbour Point's water evidence, then Rio Verde's wildfire row. Two
seconds each.*

---

## What's Next

> Certified manufacturer data in place of the last synthetic documents, more
> public datasets, and a production architecture.
>
> The idea is simple. When an engineering decision gets made, you should see the
> evidence and the assumptions behind it, not just the answer.

*On screen: the evidence panel, citations visible. Hold, then cut.*

---

## What was cut, and what it would cost to restore

| Cut | Words | Worth restoring if |
|---|---|---|
| The OCR paragraph (lower confidence, flag for manual check) | 45 | You would rather show document ingestion than the site table |
| "compares the two units and calculates the change in weight, dimensions, electrical requirements, cooling capacity, and so on" | 22 | Never. The 440 kg example does this work better. |
| "hundreds of automated tests passing" expanded to the real figure | 6 | You want the precise number: 277 |

The OCR point is the one genuinely worth missing. If you want it back, drop the
"What We Built" section and open the demo on a document upload instead.

---

## Delivery notes

**Say "missing", not "null" or "gap".** The judges are Mireye's team. "Missing"
is the word that lands.

**The wet-bulb shot is the pitch.** Everyone else's demo will show a full
dashboard. Yours shows a system that declined to fill one in, and explains why.
Give it the time.

**Demo in live mode.** With live Mireye, CH-01 lands on NEEDS INFORMATION rather
than ENGINEER REVIEW, because real evidence has real gaps. That is the more
honest demo and it matches the sentence you just said about missing data.

**Load both tabs before recording.** The first live Mireye investigation on a
cold cache takes about seven seconds, which is a long time on camera.

**If you run over:** cut the Arizona half of the findings. Virginia carries it.

**If you run short:** add *"and none of those numbers come from the language
model. It plans and explains. It never writes a number."*
