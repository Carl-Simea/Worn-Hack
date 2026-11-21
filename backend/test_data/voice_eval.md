# Voice NLU eval (qwen2.5:7b, text in)

**49/49** correct (100%). Model path avg 848 ms (p90 1243), one-word fast path avg 7 ms, rule fallbacks 1.

| ok | screen | heard | got | via | ms |
|---|---|---|---|---|---|
| ✓ | lesson | take me back home | home | model | 582 |
| ✓ | words | go back | back | model | 574 |
| ✓ | words | uh, back please | back | fast | 5 |
| ✓ | learn | can we go to the home screen | home | model | 583 |
| ✓ | home | open my journal | open | model | 1057 |
| ✓ | home | show me the daily five | open | model | 1129 |
| ✓ | home | how does this thing work | help | model | 501 |
| ✓ | home | go home then open the journal | home, open | model | 1228 |
| ✓ | home | let's exit | exit | model | 654 |
| ✓ | lesson | ok bye scribi | exit | fast | 5 |
| ✓ | home | I'm done for today | exit | model | 592 |
| ✓ | home | close the app | exit | model | 596 |
| ✓ | home | teach me something in Arabic | learn | model | 1243 |
| ✓ | home | I wanna learn some greek | learn | fast | 6 |
| ✓ | home | let's do hindi | learn | fast | 5 |
| ✓ | learn | um the russian one | learn | rules | 2021 |
| ✓ | home | teach me water in hebrew | select | model | 1549 |
| ✓ | words | let's do thank you | select | model | 1786 |
| ✓ | home | how do you say hello in Mandarin | select | fast | 8 |
| ✓ | home | I want to spell water in Hebrew | select | model | 1524 |
| ✓ | home | how do I write friend in greek | select | fast | 8 |
| ✓ | lesson | that was too fast | slower | model | 585 |
| ✓ | lesson | whoa slow down | slower | model | 572 |
| ✓ | lesson | can you speed it up | faster | model | 533 |
| ✓ | lesson | skip this one, it's too hard | skip | model | 363 |
| ✓ | lesson | say that again | repeat | model | 371 |
| ✓ | lesson | wait what did you say | repeat | model | 356 |
| ✓ | lesson | show me the strokes again | show_again | model | 412 |
| ✓ | lesson | ok I think I'm finished | check | model | 366 |
| ✓ | lesson | how did I do | check | model | 355 |
| ✓ | lesson | can you check it | check | model | 363 |
| ✓ | lesson | what does this mean | meaning | model | 358 |
| ✓ | lesson | what am I even writing | meaning | model | 375 |
| ✓ | lesson | go to the next one | next | model | 361 |
| ✓ | lesson | move on | next | model | 367 |
| ✓ | lesson | go back one | back | model | 398 |
| ✓ | home | how do I write good morning in greek | compose | fast | 13 |
| ✓ | home | help me write see you tomorrow in russian | compose | model | 973 |
| ✓ | home | write my name, Maria | write_name | fast | 6 |
| ✓ | home | can you write my name? it's Jordan | write_name | model | 6689 |
| ✓ | home | how do you write my name | ask | model | 645 |
| ✓ | home | what can I say | help | model | 506 |
| ✓ | lesson | I'm stuck, help | help | model | 576 |
| ✓ | home | yeah so the meeting got moved to three | unknown | model | 573 |
| ✓ | lesson | did you see the game last night | unknown | fast | 5 |
| ✓ | lesson | next | next | fast | 12 |
| ✓ | words | back | back | fast | 6 |
| ✓ | lesson | check | check | fast | 5 |
| ✓ | home | home | home | fast | 5 |
