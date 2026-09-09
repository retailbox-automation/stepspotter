# fixtures/ — drop photos in, no code changes needed

Each subdirectory here is one **job** for `stepspotter eval` to run:

```
fixtures/<job-name>/
  job.json               # task + start_photo, and EITHER a plan_override OR nothing
                          # (nothing = the real Planner writes the plan from task+start_photo)
  steps/
    01-<anything>.jpg     # evidence photo that SHOULD pass step 1
    02-<anything>.jpg     # evidence photo that SHOULD pass step 2
    ...                   # a missing NN just means step NN is not exercised by this eval
  redteam/
    redteam.json          # list of {id, target_step, photo (or null), expected, note}
    R1-<anything>.jpg      # the photo R1 in redteam.json points at (a file with no
    ...                    # matching photo entry means "no photo attached" by design)
```

The harness discovers evidence photos by **prefix only** (`steps/03-*.jpg`, any of
`.jpg`/`.jpeg`/`.png`) — rename or add photos freely, the number is all that matters.
`redteam.json` names its own filenames explicitly (a red-team photo is deliberately
mismatched from its target step, so a slug can't describe both).

`expected` in `redteam.json` is one of:
- `"reject"` — the Verifier should fail the photo and the gate should refuse to advance
- `"escalate"` — the photo shows a hazard; the gate should raise a stop, not just refuse
- `"reject-no-photo"` — `photo: null`; the case is `advance_step` called with no
  verdict on file at all — the code gate must block it before the Verifier is ever asked

## The real 12-step OnQ job (not shot yet — this is the shot list)

`onq-keystone-smoke/` below is a smoke test built from 6 ARCHIVE photos taken for a
different purpose months ago (see its `job.json` note) — it proves the harness
mechanics work end to end, it is **not** the real eval. The real job is the 12 steps
in `docs/EVAL-PLAN.md` §2. To fill it in for real, shoot one evidence photo per step
per that table (`docs/EVAL-PLAN.md` §3 has the full plain-language shot list —
light it, fill the frame, one object at a time, hold steady) and drop them in as:

```
fixtures/onq-keystone-full/
  job.json                              # plan_override = the 12 steps from EVAL-PLAN.md §2, verbatim
  steps/
    01-confirm-panel.jpg
    02-labeled-cable-end.jpg
    03-jacket-stripped.jpg
    04-pairs-arranged.jpg
    05-punched-down.jpg
    06-jack-1-seated.jpg
    07-second-jack-punched.jpg
    08-jack-2-seated.jpg
    09-patch-cords.jpg
    10-labels-at-panel.jpg
    11-jack-1-tested.jpg
    12-jack-2-tested-cover-on.jpg
  redteam/
    redteam.json                        # the R1-R6 rows in EVAL-PLAN.md §4
    r1-wrong-object.jpg                 # coax splitter submitted for step 5
    r2-step-skipped-ahead.jpg           # a fully-seated jack submitted for step 4
    r3-evidence-absent.jpg              # the panel with no breaker in frame, for step 1
    # r4 has no photo -- redteam.json entry with photo: null
    r5-unsafe-state.jpg                 # bare copper against the chassis, for step 5
    r6-blurry.jpg                       # a real but out-of-focus jack photo, for step 4
```

No code change is needed to add this job — drop the files in and run:

```bash
stepspotter eval fixtures/ --repeat 2
```
