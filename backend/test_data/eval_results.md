# Real-world perception eval (teammate notebook photos)

Run 2026-11-21 03:19. Inputs: `test_data/handwriting/writer{1,2,3}.jpg` + `labels.json`.

## Ink extraction on full notebook pages
Share of detected ink inside the hand-written band (rest = lines, holes, spiral, shadow false positives): writer1 100%, writer2 100%, writer3 88%

## Tier 1: ink diff (new stroke?)
Accuracy **100%** on 18 cases; false new-stroke 0, missed strokes 0; latency avg 41 ms, max 66 ms.

| case | writer 1 | writer 2 | writer 3 |
|---|---|---|---|
| camera shift 7px + 1.5° | ✅ 0.00000 | ✅ 0.00008 | ✅ 0.00000 |
| 20% dimmer | ✅ 0.00000 | ✅ 0.00000 | ✅ 0.00000 |
| shadow sweep 45% | ✅ 0.00028 | ✅ 0.00000 | ✅ 0.00015 |
| JPEG recompress q60 | ✅ 0.00000 | ✅ 0.00016 | ✅ 0.00000 |
| shift + shadow | ✅ 0.00000 | ✅ 0.00000 | ✅ 0.00006 |
| real new stroke (moved camera) | ✅ 0.00080 | ✅ 0.00081 | ✅ 0.00081 |

## Tier 2: stroke match across handwriting styles
84 renders (7 chars x 4 styles x 3 real papers). Final stroke accepted **96%**, right char scores above confusable char **86%**; latency avg 12.8 ms, max 19.9 ms (budget 300).

| style | final stroke done | right > wrong |
|---|---|---|
| print | 100% | 86% |
| cursive-ish | 86% | 86% |
| marker | 100% | 86% |
| mixed | 100% | 86% |

## Tier 3: qwen2.5vl:7b grading
Overall **93%** on 76 grades; harsh feedback 0; latency avg 2782 ms, max 5576 ms.

| case | accuracy | n |
|---|---|---|
| real: as photographed | 94% | 16 |
| real: tilted 8° + shadow | 94% | 16 |
| real: wrong target (must reject) | 100% | 16 |
| script on real paper: print | 86% | 7 |
| script on real paper: print, wrong char | 100% | 7 |
| script on real paper: mixed | 71% | 7 |
| script on real paper: mixed, wrong char | 100% | 7 |

## Tier 3 + tutor agent (the full /grade)
Right letters accepted **100%**, wrong letters rejected **100%** (28 grades, 7 targets x print/slanted+tilted+shadowed on real paper); latency avg 4969 ms, max 5613 ms (includes the tutor LLM).

Misses:
- real: as photographed: target D read 'p' (30): "The letter should be more open and rounded at the bottom."
- real: tilted 8° + shadow: target D read 'p' (30): "The letter 'p' has been written instead of 'd'."
- script on real paper: print: target ש read 'ע' (30): "The letter should have two vertical lines with the top line longer."
- script on real paper: mixed: target ש read 'ע' (30): "The letter should have two vertical lines with the top line longer."
- script on real paper: mixed: target λ read '\\' (30): "The line should be straight and vertical."
