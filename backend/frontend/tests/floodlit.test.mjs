import test from "node:test";
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
import { uploadProblem } from "../.test-build/floodlit/Upload.js";
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

test("speeds: measured, settled estimate, uncertain or none", () => {
  const flight = (f) => ({
    flight: { quality: "good", initial_speed_kmh: 151.4, ...f },
  });
  assert.deepEqual(speedOf(flight({})), { kmh: 151 });
  assert.deepEqual(
    speedOf(flight({ launch_supported: true, early_speed_kmh: 140.6 })),
    {
      kmh: 141,
    },
  );
  assert.deepEqual(speedOf(flight({ launch_supported: false })), {
    bound: true,
  });
  assert.deepEqual(
    speedOf(
      flight({
        launch_supported: false,
        settled_supported: true,
        speed_settled_kmh: 99.6,
      }),
    ),
    { kmh: 100, settled: true },
  );
  assert.deepEqual(speedOf(flight({ quality: "speed_bound" })), {
    bound: true,
  });
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
    "Choose a video first.",
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
