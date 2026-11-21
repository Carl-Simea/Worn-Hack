# Real-world perception eval (teammate notebook photos)

Run 2026-11-21 02:24. Inputs: `test_data/handwriting/writer{1,2,3}.jpg` + `labels.json`.

## Ink extraction on full notebook pages
Share of detected ink inside the hand-written band (rest = lines, holes, spiral, shadow false positives): writer1 100%, writer2 100%, writer3 88%

## Tier 1: ink diff (new stroke?)
Accuracy **100%** on 18 cases; false new-stroke 0, missed strokes 0; latency avg 49.2 ms, max 74 ms.

| case | writer 1 | writer 2 | writer 3 |
|---|---|---|---|
| camera shift 7px + 1.5° | ✅ 0.00000 | ✅ 0.00008 | ✅ 0.00000 |
| 20% dimmer | ✅ 0.00000 | ✅ 0.00000 | ✅ 0.00000 |
| shadow sweep 45% | ✅ 0.00028 | ✅ 0.00000 | ✅ 0.00015 |
| JPEG recompress q60 | ✅ 0.00000 | ✅ 0.00016 | ✅ 0.00000 |
| shift + shadow | ✅ 0.00000 | ✅ 0.00000 | ✅ 0.00006 |
| real new stroke (moved camera) | ✅ 0.00080 | ✅ 0.00081 | ✅ 0.00081 |

## Tier 2: stroke match across handwriting styles
84 renders (7 chars x 4 styles x 3 real papers). Final stroke accepted **96%**, right char scores above confusable char **86%**; latency avg 14.8 ms, max 73.7 ms (budget 300).

| style | final stroke done | right > wrong |
|---|---|---|
| print | 100% | 86% |
| cursive-ish | 86% | 86% |
| marker | 100% | 86% |
| mixed | 100% | 86% |

## Tier 3: qwen2.5vl:7b grading
Overall **67%** on 76 grades; harsh feedback 0; latency avg 4734 ms, max 8976 ms.

| case | accuracy | n |
|---|---|---|
| real: as photographed | 31% | 16 |
| real: tilted 8° + shadow | 31% | 16 |
| real: wrong target (must reject) | 100% | 16 |
| script on real paper: print | 86% | 7 |
| script on real paper: print, wrong char | 100% | 7 |
| script on real paper: mixed | 71% | 7 |
| script on real paper: mixed, wrong char | 100% | 7 |

Misses:
- real: as photographed: target B read 'b' (45): "Add more vertical line and curve."
- real: tilted 8° + shadow: target B read 'b' (45): "The letter needs more vertical alignment and straight lines."
- real: tilted 8° + shadow: target D read 'p' (30): "The letter 'p' should have a vertical line and two curved lines."
- real: as photographed: target F read 'f' (45): "The top line needs to be straight and horizontal."
- real: as photographed: target G read 'g' (45): "Add the top curve to make it more like 'G'."
- real: as photographed: target M read 'm' (45): "The letter should be capitalized and written more upright."
- real: tilted 8° + shadow: target M read 'M' (30): "The letter looks like 'M', but the top part is not closed."
- real: as photographed: target C read 'c' (45): "The loop needs to be more open and distinct."
- real: tilted 8° + shadow: target C read '' (0): "I can't see your writing, hold the paper closer."
- real: as photographed: target F read 'f' (45): "The top line needs to be straight and horizontal."
- real: tilted 8° + shadow: target F read 'f' (45): "Ensure the top line is straight and horizontal."
- real: as photographed: target G read 'g' (45): "Add more curve to the top of the letter."
