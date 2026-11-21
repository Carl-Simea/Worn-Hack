# Voice NLU eval (qwen2.5:7b, text in)

**47/49** correct (96%). Model path avg 596 ms (p90 968), one-word fast path avg 8 ms, rule fallbacks 3.

| ok | screen | heard | got | via | ms |
|---|---|---|---|---|---|
| ✓ | lesson | take me back home | home | model | 386 |
| ✓ | words | go back | back | model | 405 |
| ✓ | words | uh, back please | back | fast | 17 |
| ✓ | learn | can we go to the home screen | home | model | 401 |
| ✓ | home | open my journal | open | model | 643 |
| ✓ | home | show me the daily five | open | model | 680 |
| ✗ | home | how does this thing work | ask | model | 389 |
| ✓ | home | go home then open the journal | home, open | model | 738 |
| ✓ | home | let's exit | exit | model | 415 |
| ✓ | lesson | ok bye scribi | exit | fast | 5 |
| ✓ | home | I'm done for today | exit | model | 406 |
| ✓ | home | close the app | exit | model | 471 |
| ✓ | home | teach me something in Arabic | learn | model | 915 |
| ✓ | home | I wanna learn some greek | learn | model | 827 |
| ✓ | home | let's do hindi | learn | rules | 832 |
| ✓ | learn | um the russian one | learn | rules | 1294 |
| ✓ | home | teach me water in hebrew | select | model | 968 |
| ✓ | words | let's do thank you | select | model | 1068 |
| ✓ | home | how do you say hello in Mandarin | select | model | 1027 |
| ✓ | home | I want to spell water in Hebrew | select | model | 882 |
| ✓ | home | how do I write friend in greek | select | model | 963 |
| ✓ | lesson | that was too fast | slower | model | 412 |
| ✓ | lesson | whoa slow down | slower | model | 425 |
| ✓ | lesson | can you speed it up | faster | model | 410 |
| ✓ | lesson | skip this one, it's too hard | skip | model | 576 |
| ✓ | lesson | say that again | repeat | model | 567 |
| ✓ | lesson | wait what did you say | repeat | model | 1121 |
| ✓ | lesson | show me the strokes again | show_again | model | 577 |
| ✓ | lesson | ok I think I'm finished | check | rules | 2027 |
| ✓ | lesson | how did I do | check | model | 375 |
| ✓ | lesson | can you check it | check | model | 356 |
| ✓ | lesson | what does this mean | meaning | model | 361 |
| ✓ | lesson | what am I even writing | meaning | model | 372 |
| ✓ | lesson | go to the next one | next | model | 362 |
| ✓ | lesson | move on | next | model | 380 |
| ✓ | lesson | go back one | previous | model | 366 |
| ✓ | home | how do I write good morning in greek | compose | model | 976 |
| ✓ | home | help me write see you tomorrow in russian | compose | model | 968 |
| ✓ | home | write my name, Maria | write_name | model | 900 |
| ✓ | home | can you write my name? it's Jordan | write_name | model | 659 |
| ✓ | home | how do you write my name | ask | model | 410 |
| ✓ | home | what can I say | help | model | 359 |
| ✗ | lesson | I'm stuck, help | repeat | model | 421 |
| ✓ | home | yeah so the meeting got moved to three | unknown | model | 431 |
| ✓ | lesson | did you see the game last night | unknown | model | 467 |
| ✓ | lesson | next | next | fast | 12 |
| ✓ | words | back | back | fast | 6 |
| ✓ | lesson | check | check | fast | 5 |
| ✓ | home | home | home | fast | 5 |
