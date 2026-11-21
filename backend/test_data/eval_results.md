# Real-world perception eval (teammate notebook photos)

Run 2026-11-21 11:01. Inputs: `test_data/handwriting/writer{1,2,3}.jpg` + `labels.json`.

## Ink extraction on full notebook pages
Share of detected ink inside the hand-written band (rest = lines, holes, spiral, shadow false positives): writer1 100%, writer2 100%, writer3 88%

## Tier 1: ink diff (new stroke?)
Accuracy **100%** on 18 cases; false new-stroke 0, missed strokes 0; latency avg 39.2 ms, max 65 ms.

| case | writer 1 | writer 2 | writer 3 |
|---|---|---|---|
| camera shift 7px + 1.5° | ✅ 0.00000 | ✅ 0.00008 | ✅ 0.00000 |
| 20% dimmer | ✅ 0.00000 | ✅ 0.00000 | ✅ 0.00000 |
| shadow sweep 45% | ✅ 0.00028 | ✅ 0.00000 | ✅ 0.00015 |
| JPEG recompress q60 | ✅ 0.00000 | ✅ 0.00016 | ✅ 0.00000 |
| shift + shadow | ✅ 0.00000 | ✅ 0.00000 | ✅ 0.00006 |
| real new stroke (moved camera) | ✅ 0.00080 | ✅ 0.00081 | ✅ 0.00081 |

## Tier 2: stroke match across handwriting styles
84 renders (7 chars x 4 styles x 3 real papers). Final stroke accepted **96%**, right char scores above confusable char **86%**; latency avg 12.2 ms, max 15.9 ms (budget 300).

| style | final stroke done | right > wrong |
|---|---|---|
| print | 100% | 86% |
| cursive-ish | 86% | 86% |
| marker | 100% | 86% |
| mixed | 100% | 86% |
