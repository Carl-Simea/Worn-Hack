# Real-world perception eval (teammate notebook photos)

Run 2026-11-21 02:28. Inputs: `test_data/handwriting/writer{1,2,3}.jpg` + `labels.json`.

## Ink extraction on full notebook pages
Share of detected ink inside the hand-written band (rest = lines, holes, spiral, shadow false positives): writer1 100%, writer2 100%, writer3 88%

## Tier 1: ink diff (new stroke?)
Accuracy **100%** on 18 cases; false new-stroke 0, missed strokes 0; latency avg 54.4 ms, max 76 ms.

| case | writer 1 | writer 2 | writer 3 |
|---|---|---|---|
| camera shift 7px + 1.5° | ✅ 0.00000 | ✅ 0.00008 | ✅ 0.00000 |
| 20% dimmer | ✅ 0.00000 | ✅ 0.00000 | ✅ 0.00000 |
| shadow sweep 45% | ✅ 0.00028 | ✅ 0.00000 | ✅ 0.00015 |
| JPEG recompress q60 | ✅ 0.00000 | ✅ 0.00016 | ✅ 0.00000 |
| shift + shadow | ✅ 0.00000 | ✅ 0.00000 | ✅ 0.00006 |
| real new stroke (moved camera) | ✅ 0.00080 | ✅ 0.00081 | ✅ 0.00081 |

## Tier 2: stroke match across handwriting styles
84 renders (7 chars x 4 styles x 3 real papers). Final stroke accepted **96%**, right char scores above confusable char **86%**; latency avg 17.5 ms, max 38.6 ms (budget 300).

| style | final stroke done | right > wrong |
|---|---|---|
| print | 100% | 86% |
| cursive-ish | 86% | 86% |
| marker | 100% | 86% |
| mixed | 100% | 86% |

## Tier 3: qwen2.5vl:7b grading
Overall **87%** on 76 grades; harsh feedback 0; latency avg 2501 ms, max 6300 ms.

| case | accuracy | n |
|---|---|---|
| real: as photographed | 94% | 16 |
| real: tilted 8° + shadow | 75% | 16 |
| real: wrong target (must reject) | 94% | 16 |
| script on real paper: print | 86% | 7 |
| script on real paper: print, wrong char | 100% | 7 |
| script on real paper: mixed | 57% | 7 |
| script on real paper: mixed, wrong char | 100% | 7 |

Misses:
- real: as photographed: target D read 'p' (30): "The letter should be more open and rounded at the bottom."
- real: tilted 8° + shadow: target D read 'p' (30): "The letter should be more rounded and open at the bottom."
- real: tilted 8° + shadow: target B read '' (0): "I can't see your writing, hold the paper closer."
- real: tilted 8° + shadow: target G read '' (0): "I can't see your writing, hold the paper closer."
- real: wrong target (must reject): target Q read 'Q' (65): "Good, Q is readable."
- real: tilted 8° + shadow: target K read '' (0): "I can't see your writing, hold the paper closer."
- script on real paper: mixed: target न read 'त' (45): "The line should be straight and the bottom part of 'त' needs to extend further down."
- script on real paper: print: target ש read 'ב' (30): "The letter should have two vertical lines and a curve at the bottom."
- script on real paper: mixed: target ש read 'ע' (30): "The letter should have two vertical lines and a horizontal line."
- script on real paper: mixed: target λ read '\\' (45): "The line should be straight and vertical."
