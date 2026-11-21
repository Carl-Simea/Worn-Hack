// node glasses-android/tests/commands.test.js — every phrasing must map to the right action.
var C = require("../app/src/main/assets/ui/commands.js");
var cases = [
  ["home", {}, "home"], ["go home", {}, "home"], ["take me home", {}, "home"], ["um take me back home please", {}, "home"],
  ["hey Scribi, main menu", {}, "home"], ["start over", {}, "home"], ["Go home.", { screen: "lesson" }, "home"],
  ["back", {}, "back"], ["go back", {}, "back"], ["undo", {}, "back"],
  ["exit", {}, "exit"], ["close", {}, "exit"], ["bye", {}, "exit"], ["okay bye scribi", {}, "exit"], ["I'm done", { screen: "home" }, "exit"],
  ["learn Hebrew", {}, "learn:hebrew"], ["teach me Greek", {}, "learn:greek"], ["switch to Chinese", {}, "learn:mandarin"],
  ["let's do Arabic", {}, "learn:arabic"], ["can you open russian please", {}, "learn:russian"], ["Hindi", {}, "learn:hindi"],
  ["learn mandrin", {}, "learn:mandarin"],
  ["help me write good luck in Greek", {}, "compose:good luck:greek"], ["how do I write water in hindi", {}, "compose:water:hindi"],
  ["write friend", { lang: "russian" }, "compose:friend:russian"], ["write this word", {}, "open:compose"],
  ["how do I write my name", {}, "open:name"], ["write my name", {}, "open:name"], ["my name is Maria", {}, "write_name:Maria"],
  ["um, my name's Sam", {}, "write_name:Sam"],
  ["next", { screen: "lesson" }, "next"], ["okay next", { screen: "lesson" }, "next"], ["say that again", {}, "repeat"],
  ["slower please", {}, "slower"], ["slow down", {}, "slower"], ["I'm done", { screen: "lesson" }, "check"], ["check", { screen: "lesson" }, "check"],
  ["skip this one", {}, "skip"], ["what does this mean", {}, "meaning"], ["help", {}, "help"], ["what can I say", {}, "help"],
  ["are you ready", {}, null], ["that's the thing that's definitely", {}, null], ["okay I'm gonna ask you again", {}, null]
];
var pass = 0, fail = 0;
cases.forEach(function (c) {
  var r = C.command(c[0], c[1]), got = null;
  if (r) {
    got = r.intent;
    if (r.intent === "learn") got += ":" + r.args.lang;
    if (r.intent === "open") got += ":" + r.args.screen;
    if (r.intent === "compose") got += ":" + r.args.text + ":" + r.args.lang;
    if (r.intent === "write_name") got += ":" + r.args.name;
  }
  if (got === c[2]) pass++; else { fail++; console.log("FAIL  " + JSON.stringify(c[0]) + "  expected " + c[2] + "  got " + got); }
});
console.log(pass + "/" + cases.length + " pass");
process.exit(fail ? 1 : 0);
