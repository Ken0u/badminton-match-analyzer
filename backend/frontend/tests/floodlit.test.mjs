import test from "node:test";
import { replayActor, replaySamples } from "../src/floodlit/replay-track.js";
import { READY, gripAt, strokeKeys, swingPose } from "../src/floodlit/strokes.js";
import assert from "node:assert/strict";
import {
  applyH,
  clock,
  firstName,
  inv3,
  matchHome,
  nameOf,
  positionAt,
  prepareMatch,
  ralliesWon,
  rallyEnd,
  rallySwaps,
  shotLabel,
  speedOf,
  teamName,
} from "../.test-build/floodlit/model.js";
import { parseRoute } from "../.test-build/floodlit/shell.js";
import { checkLink, uploadProblem } from "../.test-build/floodlit/Upload.js";
import { partnersSplit } from "../.test-build/floodlit/Names.js";
import { STAGE_DETAIL } from "../.test-build/floodlit/Processing.js";
import { errorText } from "../.test-build/floodlit/api.js";
import { ApiError } from "../.test-build/api/client.js";

const players = [
  { id: "P1", name: "Ann Lee", team: "T1" },
  { id: "P2", name: "Ann Park", team: "T1" },
  { id: "P3", name: "Cy", team: "T2" },
  { id: "P4", name: "", team: "T2" },
];
const named = { analysis: { players } };

test("routes are hash paths with a 16-hex match id", () => {
  assert.deepEqual(parseRoute(""), { view: "landing" });
  assert.deepEqual(parseRoute("#/"), { view: "landing" });
  assert.deepEqual(parseRoute("#/matches"), { view: "matches" });
  assert.deepEqual(parseRoute("#/upload"), { view: "upload" });
  const id = "c406a1187130b845";
  assert.deepEqual(parseRoute(`#/match/${id}/processing`), {
    view: "processing",
    id,
  });
  assert.deepEqual(parseRoute(`#/match/${id}/names`), { view: "names", id });
  assert.deepEqual(parseRoute(`#/match/${id}`), {
    view: "match",
    id,
    tab: "watch",
  });
  assert.deepEqual(parseRoute(`#/match/${id}/analysis?t=12`), {
    view: "match",
    id,
    tab: "analysis",
  });
  assert.equal(parseRoute("#/match/../../etc/watch").view, "missing");
  assert.equal(parseRoute(`#/match/${id}/watch/extra`).view, "missing");
  assert.equal(parseRoute("#/library").view, "missing");
});

test("each state opens where the match stands", () => {
  assert.equal(matchHome("a", "ready"), "#/match/a/watch");
  assert.equal(matchHome("a", "needs_names"), "#/match/a/names");
  for (const s of ["queued", "running", "failed", "paused"])
    assert.equal(matchHome("a", s), "#/match/a/processing");
  for (const stage of [
    "Downloading the video",
    "Finding players",
    "Tracking the shuttle",
    "Building the analysis",
  ])
    assert.ok(STAGE_DETAIL[stage]);
});

test("names fall back to the id and clash to full names", () => {
  assert.equal(nameOf(named, "P4"), "P4");
  assert.equal(nameOf(named, null), "Unknown player");
  assert.equal(firstName(named, "P1"), "Ann Lee");
  assert.equal(firstName(named, "P3"), "Cy");
  assert.equal(teamName(named, "T1"), "Ann Lee & Ann Park");
});

test("speeds: fitted launch speed, too fast, or none", () => {
  const flight = (f) => ({
    flight: { quality: "good", initial_speed_kmh: 151.4, ...f },
  });
  assert.deepEqual(speedOf(flight({})), { kmh: 151 });
  // Launch-support diagnostics never hide or replace the fitted speed.
  assert.deepEqual(
    speedOf(flight({ launch_supported: true, early_speed_kmh: 140.6 })),
    { kmh: 151 },
  );
  assert.deepEqual(
    speedOf(
      flight({
        launch_supported: false,
        settled_supported: true,
        speed_settled_kmh: 99.6,
      }),
    ),
    { kmh: 151 },
  );
  assert.deepEqual(
    speedOf(flight({ quality: "speed_bound", settled_supported: true })),
    { bound: true },
  );
  assert.equal(speedOf(flight({ quality: "poor_fit" })), null);
  assert.equal(speedOf({ flight: null }), null);
  assert.equal(
    shotLabel({ kind: "serve", serve_type: "short", family: null }),
    "serve_short",
  );
  assert.equal(shotLabel({ kind: "shot", family: null }), "unknown");
});

test("rally helpers: end at the landing, wins, swaps by frame range", () => {
  const rallies = [
    {
      id: "rally-1",
      start_frame: 0,
      end_frame: 50,
      end_s: 2,
      shots: [{ landing: { time_s: 2.6 } }],
      outcome: { winner_team: "T1" },
    },
    {
      id: "rally-2",
      start_frame: 80,
      end_frame: 120,
      end_s: 5,
      shots: [],
      outcome: null,
    },
    {
      id: "rally-3",
      start_frame: 150,
      end_frame: 200,
      end_s: 8,
      shots: [],
      outcome: { winner_team: "T2" },
    },
  ];
  assert.equal(rallyEnd(rallies[0]), 2.6);
  assert.equal(rallyEnd(rallies[1]), 5);
  assert.deepEqual(ralliesWon(rallies), { T1: 1, T2: 1 });
  const analysis = {
    overrides: [
      {
        persons: ["P1", "P2"],
        start_frame: 80,
        end_frame: 120,
        rally_id: "rally-9",
      },
    ],
  };
  assert.equal(rallySwaps(analysis, rallies[0]).length, 0);
  assert.equal(rallySwaps(analysis, rallies[1]).length, 1);
  assert.equal(rallySwaps({}, rallies[1]).length, 0);
});

test("homography inverse round-trips and tracks interpolate at 10 Hz", () => {
  const H = [
    [2, 0.1, 0.3],
    [0.05, 3, 0.2],
    [0.01, 0.02, 1],
  ];
  const [x, y] = applyH(H, 0.4, 0.6);
  const [u, v] = applyH(inv3(H), x, y);
  assert.ok(Math.abs(u - 0.4) < 1e-9 && Math.abs(v - 0.6) < 1e-9);
  const analysis = {
    court: { views: [{ start_frame: 0, end_frame: 10, homography: H }] },
    tracks: {
      rate_hz: 10,
      persons: [
        { person_id: "P1", x: [1, 2, null, null, 5], y: [1, 1, null, null, 1] },
      ],
    },
    players,
  };
  const match = prepareMatch("m", analysis, null);
  assert.deepEqual(positionAt(match, "P1", 0.05), { x: 1.5, y: 1 });
  assert.deepEqual(positionAt(match, "P1", 0.25), { x: 2, y: 1 });
  assert.equal(positionAt(match, "P9", 0.25), null);
  assert.equal(clock(125.9), "2:05");
  assert.equal(clock(null), "0:00");
});

test("upload checks every name before sending", () => {
  const file = { name: "m.mp4" };
  assert.equal(
    uploadProblem(null, "singles", { T1: ["a"], T2: ["b"] }),
    "Choose a video or paste a YouTube link first.",
  );
  assert.match(
    uploadProblem(file, "doubles", { T1: ["a", ""], T2: ["b", "c"] }),
    /every name/,
  );
  assert.match(
    uploadProblem(file, "doubles", { T1: ["a", "B"], T2: ["b", "c"] }),
    /different/,
  );
  assert.equal(
    uploadProblem(file, "doubles", { T1: ["a", "d"], T2: ["b", "c"] }),
    "",
  );
  // Singles only reads the first field of each side.
  assert.equal(
    uploadProblem(file, "singles", { T1: ["a", "x"], T2: ["b", "x"] }),
    "",
  );
});

test("a pasted YouTube link is tidied and obvious mistakes are named", () => {
  const ok = (raw, url) =>
    assert.deepEqual(checkLink(raw), { url, problem: "" });
  ok(
    "https://www.youtube.com/watch?v=abcdefghijk",
    "https://www.youtube.com/watch?v=abcdefghijk",
  );
  ok("  youtu.be/abcdefghijk?si=x ", "https://youtu.be/abcdefghijk?si=x");
  ok(
    "http://m.youtube.com/watch?v=abcdefghijk&t=30",
    "https://m.youtube.com/watch?v=abcdefghijk&t=30",
  );
  ok(
    "https://youtube.com/shorts/abcdefghijk",
    "https://youtube.com/shorts/abcdefghijk",
  );
  ok("", "");
  const bad = (raw, pattern) => assert.match(checkLink(raw).problem, pattern);
  bad("https://vimeo.com/123", /not a YouTube link/);
  bad("ftp://youtu.be/abcdefghijk", /not a YouTube link/);
  bad("https://www.youtube.com/watch?v=abcdefghijk&list=PL1", /playlist/);
  bad("https://www.youtube.com/playlist?list=PL1", /playlist/);
  bad("https://www.youtube.com/@club", /one video/);
  bad("https://youtu.be/short", /one video/);
  bad("https://exa mple", /does not look like a link/);
  // The link stands in for the file; a bad link is the first problem named.
  const names = { T1: ["a"], T2: ["b"] };
  assert.equal(
    uploadProblem(null, "singles", names, "youtu.be/abcdefghijk"),
    "",
  );
  assert.match(
    uploadProblem(null, "singles", names, "https://vimeo.com/1"),
    /YouTube/,
  );
  assert.match(
    uploadProblem(
      null,
      "singles",
      { T1: ["a"], T2: [""] },
      "youtu.be/abcdefghijk",
    ),
    /every name/,
  );
});

test("partners entered together must stay on one side", () => {
  const people = [
    { id: "P1", team: "T1" },
    { id: "P2", team: "T1" },
    { id: "P3", team: "T2" },
    { id: "P4", team: "T2" },
  ];
  const teams = { T1: ["Ann", "Bo"], T2: ["Cy", "Dee"] };
  assert.equal(
    partnersSplit(people, { P1: "Bo", P2: "Ann", P3: "Dee", P4: "Cy" }, teams),
    false,
  );
  assert.equal(
    partnersSplit(people, { P1: "Cy", P2: "Bo", P3: "Ann", P4: "Dee" }, teams),
    true,
  );
  assert.equal(
    partnersSplit(
      people.slice(0, 1),
      { P1: "Ann" },
      { T1: ["Ann"], T2: ["Cy"] },
    ),
    false,
  );
});

test("errors read as plain sentences", () => {
  assert.equal(
    errorText(new ApiError(409, "Another job is running", "", "/api/matches")),
    "Another job is running.",
  );
  assert.equal(
    errorText(new ApiError(422, [{ msg: "Names must differ" }], "", "/x")),
    "Names must differ.",
  );
  assert.equal(
    errorText(new ApiError(413, null, "", "/x")),
    "That file is too large for the server.",
  );
  assert.match(errorText(new TypeError("Failed to fetch")), /Could not reach/);
});

test("replay swings have distinct finishes and carry the racket face through impact", () => {
  const finishes = new Set();
  for (const label of ["smash", "clear", "drop", "drive", "net", "lift", "block", "push", "net_kill", "serve", "serve_short", "serve_long"]) {
    const keys = strokeKeys(label, false);
    const at = t => swingPose(label, false, t);
    assert.deepEqual(at(keys[0][0]), READY);
    assert.deepEqual(at(keys.at(-1)[0]), READY);
    finishes.add(JSON.stringify(at(0.08)));
    const eps = 1e-5;
    const rateIn = (at(0).roll - at(-eps).roll) / eps;
    const rateOut = (at(eps).roll - at(0).roll) / eps;
    assert.ok(rateIn > 0 && Math.abs(rateIn - rateOut) < 0.02, label);
    assert.notEqual(at(-0.05).rx, at(0.05).rx, label);
  }
  assert.equal(finishes.size, 12);
  assert.notDeepEqual(swingPose("drive", false, 0), swingPose("drive", true, 0));
  assert.deepEqual(swingPose("unclassified", false, 0), swingPose("unknown", false, 0));
});

test("the idle racket is edge-on; block preparation uses the thumb bevel even before a forehand change", () => {
  const idle = gripAt(undefined, undefined, Infinity);
  assert.ok(Math.abs(Math.cos(idle.angle)) < 0.20);
  for (const side of ["forehand", "backhand", "unknown"]) {
    assert.deepEqual(gripAt("block", side, -1), idle);
    assert.deepEqual(gripAt("block", side, 1), idle);
    assert.equal(gripAt("block", side, -0.18).thumb, 1);
  }
  assert.deepEqual(gripAt("block", "forehand", 0), gripAt("push", "forehand", 0));
  assert.equal(gripAt("block", "unknown", 0).thumb, 1);
  assert.equal(gripAt("push", "backhand", 0).thumb, 1);
});

test("overheads turn through contact, blocks lower the head, and pushes extend without a wrist flick", () => {
  for (const label of ["smash", "clear"]) {
    const roll = t => swingPose(label, false, t).roll;
    assert.ok(roll(0) - roll(-0.065) > 1);
    assert.ok(roll(0.10) > roll(0));
  }
  const down = swingPose("block", true, -0.19);
  assert.ok(Math.cos(down.sx + down.ex + down.rx) > 0.5);
  for (const backhand of [false, true]) {
    const pre = swingPose("push", backhand, -0.13), post = swingPose("push", backhand, 0.085);
    assert.ok(post.ex - pre.ex > 0.65);
    assert.ok(Math.abs(post.rx - pre.rx) < 0.04);
    assert.ok(Math.abs(post.roll - pre.roll) < 0.30);
  }
});

test("a doubles rear player covers a tracking gap and honors only their labeled shot positions", () => {
  const rear = { x: Array(25).fill(null), y: Array(25).fill(null) };
  rear.x[24] = 4; rear.y[24] = 1;
  const front = { x: Array.from({length:25}, (_,i) => 2+i/12), y: Array(25).fill(4) };
  const players = [{id:"rear",team:"A"},{id:"front",team:"A"}];
  const match = { analysis:{players,tracks:{rate_hz:10}}, trackIndex:new Map([["rear",rear],["front",front]]) };
  const shots = [{hitter_id:null,time_s:0.3,hitter_position:{x:6,y:6}},
    {hitter_id:"front",time_s:0.4,hitter_position:{x:6,y:5}},
    {hitter_id:"rear",time_s:1.3,hitter_position:{x:3,y:1.5}},
    {hitter_id:"rear",time_s:2.4,hitter_position:{x:1,y:5}}];
  const path = replaySamples(match, "rear", 0, 24, shots, {x:3,y:6});
  assert.notEqual(path[0].x, path[6].x);
  assert.ok(path.every(p => p.y < 4));
  assert.deepEqual(path[13], shots[2].hitter_position);
  assert.deepEqual(path[24], {x:4,y:1});
  assert.equal(rear.x[13], null);
  players.pop(); // No doubles partner: interpolate actual anchors, don't stage coverage.
  const solo = replaySamples(match, "rear", 0, 24, shots, {x:3,y:6});
  assert.deepEqual(solo[0], shots[2].hitter_position);
  assert.ok(solo[18].x > 3 && solo[18].x < 4);
});

test("a smash with an anonymous contact gets the remaining avatar, not a guessed hitter label", () => {
  const roster = ["A", "B", "C", "D"].map(id => ({id}));
  const players = ["A", "D", null, "B"].map((person_id,i) => ({person_id,position:{x:i,y:2}}));
  const shot = { family:"smash", hitter_id:null, hitter_position:{x:2,y:2}, players };
  assert.equal(replayActor(shot, roster), "C");
  assert.equal(shot.hitter_id, null);
  assert.equal(replayActor({...shot, hitter_id:"D"}, roster), "D");
  assert.equal(replayActor({...shot, players:players.slice(1)}, roster), null);
  assert.equal(replayActor({...shot, players:[...players.slice(0,3),players[0]]}, roster), null);
  assert.equal(replayActor({...shot, hitter_position:{x:2.1,y:2}}, roster), null);
});
