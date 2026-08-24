# Two-minute video script

Target: **1:55**. Read at a normal pace, do not rush. Word counts are per block
so you can time yourself; ~150 words per minute is comfortable.

Record the screen at 1920x1080. Have both workflows already loaded in tabs so
nothing has to load on camera.

---

## 0:00 - 0:22 · The problem (56 words)

> A hyperscale data centre gets decided twice. Once when you pick the site, and
> again every time a piece of equipment gets substituted during construction.
>
> Both decisions turn on physical facts. And in practice, both get made on
> numbers nobody can trace.
>
> The failure isn't missing data. It's that missing data quietly becomes a
> number.

**On screen:** the ranked site table, sitting still. Don't click yet.

---

## 0:22 - 0:40 · The idea (45 words)

> A blank cell scores as zero. A nearby measurement gets used because it's the
> closest thing available. Each one looks exactly like a measurement.
>
> So we built the whole system on one rule: a value nobody measured is missing.
> Missing never becomes zero.

**On screen:** hover an open Information Gap so the *"missing"* badge is visible.

---

## 0:40 - 1:05 · Before construction (61 words)

> This is Mireye's physical-world data, live. Thirty parameters per site,
> scored across eight dimensions.
>
> Here's what that rule buys you. Mireye publishes a design *wet-bulb*
> temperature. Our model needs *dry-bulb*. Both are temperatures in Celsius, so
> nothing would break if we swapped them. The score would just be wrong.
>
> So it's stored as contextual evidence. Visible, cited, and structurally unable
> to close that gap.

**On screen:** open the evidence drawer on `ambient_design_db_c`. Show the proxy
label and the note next to it. This is the single most important shot in the
video.

---

## 1:05 - 1:28 · What it caught (56 words)

> Two things the system told us that we didn't know.
>
> Harbour Point, Virginia: groundwater at six thousand six hundred milligrams
> per litre. That's brackish. It changes the entire cooling design.
>
> Rio Verde Mesa, Arizona: sits inside Tonto National Forest, and FEMA rates it
> Very High for wildfire. Two independent public datasets, agreeing.

**On screen:** Harbour Point's water evidence, then Rio Verde's protected-area
and wildfire rows. Let each sit for two seconds.

---

## 1:28 - 1:45 · During construction (43 words)

> Second workflow. A chiller gets substituted. The system computes fifteen
> unit-checked deltas, runs nine verification gates, and flags where structural
> review is *required*.
>
> It never says the roof is fine. That's the engineer's call, and they carry the
> liability.

**On screen:** the CH-01 change, deltas table, then the decision state.

---

## 1:45 - 1:55 · Impact (34 words)

> A campus is a one-to-three-billion-dollar commitment, decided in weeks on the
> thinnest evidence in the project's life.
>
> This gives an engineer something they can actually defend. Every number, with
> where it came from.

**On screen:** the evidence panel with citations visible. Hold, then cut.

---

## Notes

**Say "missing", not "null" or "gap".** The judges are Mireye's team, not
engineers reading your schema. "Missing" is the word that lands.

**The wet-bulb shot is the whole pitch.** If you only get one thing across, it's
that the system refuses to use a number that would have made it look better.
Everyone else's demo will show a filled dashboard. Yours shows a system that
declined to fill one, and says why.

**Don't read the feature list.** Fifteen deltas and nine gates get one sentence
between them. The counts prove it's real; naming them all proves nothing and
costs twenty seconds you need elsewhere.

**Show live mode.** With live Mireye, CH-01 lands on NEEDS INFORMATION rather
than ENGINEER REVIEW, because real evidence has real gaps. That's the more
honest demo and it matches what you just said about missing data.

**If you run over:** cut the Rio Verde half of the findings block. Harbour Point
alone carries it.

**If you run short:** add one line after the deltas - *"and every one of those
comes from tested Python, not from the language model. The model plans and
explains; it never writes a number."*
