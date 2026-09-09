# Spike A — Bedrock vision via Strands: verdicts + bounding boxes

**Date:** 2026-09-09 · **Script:** `spikes/spike_vision.py` · **Raw:** `spikes/out/raw-results.json`
**Model actually used:** `global.anthropic.claude-sonnet-4-6` (Strands/Bedrock default with no `model_id`), region `us-east-1`. Haiku fallback path never triggered.
**Input:** 6 real photos of a home OnQ low-voltage panel + wall jacks, downscaled to max 1280 px, JPEG q88.

## Verdict — **PASS**

| Gate | Bar | Result |
|---|---|---|
| False/unverifiable claims rejected | ≥3/4 | **4/4** |
| True claims accepted | ≥3/4 | **4/4** |
| Boxes at least "rough" | ≥60% | **13/14 (93%)** |

The verdict half is strong. The localization half technically clears the bar but is **not trustworthy for precise callouts** — see §4.

## 1. Part 2 — VERDICT results (8/8 correct)

| # | Photo | Claim | Exp | Got | Conf | Reason (model) |
|---|---|---|---|---|---|---|
| 1 | 01-panel-overview | panel door removed, inside visible | T | **T** ✅ | 0.97 | "door is clearly removed and the interior is fully visible…" |
| 2 | 01-panel-overview | keystone jack installed on end of blue cable | F | **F** ✅ | 0.82 | "wires exposed/untwisted rather than a keystone jack… no keystone jack connector visible" |
| 3 | 05-office-jack-open | jack open, wire pairs terminated into it | T | **T** ✅ | 0.92 | "faceplate removed, back-box exposed… blue, orange, green pairs terminated into the keystone module" |
| 4 | 05-office-jack-open | circuit breaker is switched OFF | F | **F** ✅ | 0.97 | "**No circuit breaker is visible in this photo**… no breaker panel or breaker switch present" |
| 5 | 03-telecom-module | blue cables punched down into telecom module | T | **T** ✅ | 0.92 | "visibly punched down into the punch-down terminals/IDC blocks on the labeled TELECOM module" |
| 6 | 03-telecom-module | the two blue cables have been removed from the phone block | F | **F** ✅ | 0.82 | "clearly present and attached, not removed" |
| 7 | 06-dining-node | a white network cable is present | T | **T** ✅ | 0.95 | "white network cable with visible 24AWG markings… held in the hand" |
| 8 | 06-dining-node | the cable is plugged into a network switch | F | **F** ✅ | 0.85 | "**No network switch is visible**… cable is not yet plugged into any device" |

**Key finding:** case #4 is the one that matters most for StepSpotter — the claim is about something *entirely absent from the frame*. The model refused correctly, at the **highest confidence of all eight (0.97)**, and named the absence explicitly. It did not hallucinate a breaker. Case #8 did the same and additionally corrected the object ("appears to be a router or access point, not a switch"). Refusal-on-absent-evidence works, driven by the system prompt line *"If the relevant thing is not visible in the frame … return passed=false and say the evidence is not visible."*

**Reproducibility:** the 8 verdict cases were run **twice** (two independent invocations, fresh agents). **The booleans were identical both times, 8/8 → 8/8.** The `passed` flag looks stable.

**But `confidence` is NOT stable.** Case #2 ("keystone jack installed on the blue cable") returned **0.82 on run 1 and 0.20 on run 2** — same photo, same claim, same correct `passed=false`. True-accepts were stable and high across both runs (0.92–0.97); it is the *rejections* whose confidence swings.

⚠️ **Consequence: do not gate on `confidence`.** An earlier draft of this doc proposed a 0.85 auto-pass threshold — run 2 kills that idea, and a threshold like it would have flipped this case's routing between two runs for no reason. **Use the boolean, and use the `reason` text.** If a numeric gate is needed later it must be built on a real eval sweep (n≫8, repeated seeds), not on this sample.

## 2. Part 1 — LOCATE results (14 boxes, judged by eye on the rendered overlays)

Verdict per box: **hit** = tight and on the object · **rough** = contains the object but loose/over-inclusive · **miss** = does not overlap the object.

| Photo | Object | Box (x0,y0,x1,y1) | Judged | Note |
|---|---|---|---|---|
| 01 | blue Cat5e cables | .13,.25–.72,.78 | rough | swallows the whole panel + blank wall below |
| 01 | black coax splitter | .35,.47–.60,.58 | **miss** | splitter is at ≈y .36–.46; box landed a full band **below** it, on coiled cable/white pipe |
| 01 | cut blue cable hanging outside | .22,.62–.48,.87 | rough | contains the RJ45 end, extends well past it |
| 02 | blue Cat5e cables | .00,.18–.75,.72 | rough | very loose |
| 02 | black coax cables | .10,.42–.95,.95 | rough | very loose |
| 02 | metal splitter | .60,.47–.95,.72 | rough | Holland GHPNA-3 is ≈.72,.36–.87,.58 → box offset down, ~40% overlap |
| 03 | telecom punch-down module | .08,.38–.82,.65 | rough | covers the punch-down rows, top of module clipped |
| 03 | blue cables | .00,.00–.85,.55 | rough | whole upper half |
| 03 | black coax connectors | .05,.52–.35,.72 | **hit** | tight around both F-connectors |
| 04 | wall plate | .27,.42–.75,.87 | rough | shifted down, clips top of the yellow insert |
| 04 | keystone jack opening | .33,.49–.68,.82 | **hit** | on the RJ45 opening, slight bottom overhang |
| 05 | keystone jack | .28,.78–.58,1.00 | rough | top edge correct, runs to image bottom |
| 05 | terminated wire pairs | .27,.60–.55,.82 | **hit** | on the colour-coded pairs |
| 06 | white cable | .10,.28–.55,.92 | rough | contains the full cable run, plus hand + router |

**3 hit / 10 rough / 1 miss.** Two systematic biases, both visible across photos:
1. **Downward/oversized drift** — boxes routinely sit lower and larger than the object (01 splitter, 02 splitter, 04 plate, 05 jack).
2. **Size dependency** — large, high-contrast subjects (cable runs, the RJ45 opening, wire pairs) are fine; **small hardware in clutter (splitters, F-connectors) is where it fails.** The single outright miss and the two worst roughs are all small metal parts inside a busy panel.

## 3. Part 3 — 4×4 grid-cell control (does a coarser format fix it?)

Same objects, same photos, asked for grid cells (A–D left→right, 1–4 top→bottom) instead of boxes.

| Photo | Object | Cells returned | Judged |
|---|---|---|---|
| 01 | blue Cat5e cables | A2,B2,C2,A3,B3,C3,B4,C4 | rough (adds empty A3/B4/C4) |
| 01 | black coax splitter | B3,C3 | **wrong** — splitter is in **B2** |
| 01 | cut blue cable | B4,C4 | **wrong** — cable end is in **B3** |
| 02 | metal splitter | C3,D3 | rough (object spans C2/D2/C3/D3) |
| 03 | telecom punch-down module | A3–D3, A4–D4 | rough (module is rows 2–3, answer is rows 3–4) |
| 03 | black coax connectors | A3,B4,C4 | rough (A3 right, B4 should be B3) |
| 04 | keystone jack opening | B3,C3 | **hit** |
| 05 | keystone jack / wire pairs | B3,C3,B4,C4 / B3,C3,B2,C2 | rough (over-inclusive both) |
| 06 | white cable | B2,C2,B3,C3,A3,A4,B4 | rough (traces the run correctly) |

**The grid did NOT fix the localization error — it reproduced it.** On photo 01 the grid put the coax splitter one row too low, exactly like the bounding box did, and the cut cable one row too low as well. The failure is in the model's **spatial estimate**, not in the output format. What the grid *does* change is the failure's appearance: an over-inclusive set of cells reads as "somewhere around here", whereas a confidently-drawn tight rectangle on an empty patch of wall reads as a false assertion.

## 4. Recommendation for step cards

**Do not make the step card depend on precise localization from the model.**

1. **The verdict + the written reason is the product.** 8/8 including 4/4 refusals, with reasons that name the missing object. That alone drives a step card ("not done — no breaker is visible in this photo, retake showing the panel").
2. **Boxes: use as a soft highlight, never as an assertion.** Render them with a translucent fill and a hedged caption ("roughly here"), not a crisp tight rectangle with a pointer. Consider suppressing any box whose area is <3% of the frame — the small-object boxes are where it lied.
3. **Grid over bbox when a highlight is required for a small part.** Not because it is more accurate (it is not — §3), but because the wrong answer degrades gracefully: a highlighted 4×4 cell block says "look in this area", a wrong tight box says "it is exactly there". Cost is identical (~3 s).
4. **Best of both, if we want one:** ask for a box, snap it to the containing grid cells, render the cells. Keeps the model's ranking of where to look, discards its false precision.
5. **Never crop the photo using model boxes** for a "here is your evidence" thumbnail — the 01 splitter crop would have shown a white pipe.

## 5. Exact API shapes that worked (strands 1.54.0, verified by introspection + live runs)

```python
from strands import Agent
from strands.models import BedrockModel

# no model_id -> default global.anthropic.claude-sonnet-4-6
agent = Agent(model=BedrockModel(region_name="us-east-1"),
              system_prompt=SYSTEM, callback_handler=None)

# content blocks: Bedrock converse shape, matches strands.types.media.ImageContent
blocks = [{"text": prompt},
          {"image": {"format": "jpeg", "source": {"bytes": jpeg_bytes}}}]

# A) used in this spike (works, but DEPRECATED in 1.54.0):
result = agent.structured_output(StepVerdict, blocks)          # -> StepVerdict

# B) non-deprecated form (verified live, same result, 5.0 s):
res = agent(blocks, structured_output_model=StepVerdict)        # -> AgentResult
verdict = res.structured_output                                 # -> StepVerdict
```

`ContentBlock` keys (introspected): `text, image, video, audio, document, toolUse, toolResult, cachePoint, guardContent, reasoningContent, citationsContent`. `ImageContent = {"format": Literal["png","jpeg","gif","webp"], "source": {"bytes": bytes}}` — `format` is a bare string, **not** a MIME type.

**Latency (single image, structured output, no tools):** locate 2.5–4.5 s · verdict 3.1–5.5 s · grid 2.3–3.3 s (across both runs). Median ≈3.5 s. Budget ~4 s per step check, worst seen 5.5 s.

## 6. Gotchas

- **`Agent.structured_output(...)` is deprecated in 1.54.0** — DeprecationWarning points to passing `structured_output_model=` into the invocation instead (form B above). Use B in the product code.
- **Pydantic `Field(ge=0, le=1)` on box coords held** — no out-of-range coords came back across 40+ boxes, so the JSON-schema constraints are being enforced. Constrain in the schema, don't post-clamp.
- **"Omit objects that are not visible" works.** The model returned only the objects present (e.g. 1 box for photo 06) instead of inventing boxes to fill the list. Same instruction is what makes verdict refusal work — this is one behaviour, not two.
- **Origin must be stated.** Both prompts spell out "(0,0) is TOP-LEFT". Untested whether omitting it flips the axis, but do not omit it.
- **Rejection confidence is run-to-run unstable** (0.82 vs 0.20 for an identical call) while the boolean is not — see §1. Any confidence-based routing needs its own eval before it can be trusted.
- **A fresh `Agent` per call** — reusing one agent across images leaks the previous photo into conversation history.
- **Bedrock `ValidationException … Operation not allowed` = the env export did not reach the process** (ambient `~/.aws/credentials` is a different account), **not** throttling. Export and run in the same shell command.
- **Downscale to 1280 px before sending** — originals are ~1000×1300 already, so this is cheap insurance, not a bottleneck.
- Photo `04-office-jack-front` is a near-macro of a single yellow keystone insert; calling it a "wall plate" confused the labelling. Name objects in the prompt the way they appear at that zoom level.

## 7. Files produced

- `spikes/spike_vision.py` — the spike (locate / verdict / grid)
- `spikes/out/raw-results.json` — all boxes, verdicts, cells, timings
- `spikes/out/<photo>-locate.jpg` × 6 — bounding-box overlays
- `spikes/out/<photo>-grid.jpg` × 6 — 4×4 grid-cell overlays
