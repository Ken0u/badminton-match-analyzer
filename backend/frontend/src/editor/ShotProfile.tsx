import { memo, useMemo, useState } from "react";
import { clock, pretty } from "./model.js";
import type { Document, Event } from "./model.js";

export const profileFamilies = [
  "clear",
  "lift",
  "net",
  "drop",
  "smash",
  "drive",
  "other",
  "unknown",
] as const;
export const profileSides = ["forehand", "backhand", "unknown"] as const;
export type ProfileReview = "reviewed" | "all";
type Family = (typeof profileFamilies)[number];
type Side = (typeof profileSides)[number];
export const profileStatus = (event: Event) =>
  event.status === "reviewed" || event.status === "corrected"
    ? "reviewed"
    : event.status === "predicted"
      ? "predicted"
      : "unknown";

/** Derive every displayed count and source link from one annotation snapshot.
 * Missing status is unresolved, even though the API normally supplies defaults.
 */
export function buildShotProfile(
  doc: Document,
  frameCount: number,
  review: ProfileReview = "reviewed",
  hitter = "all",
) {
  const seen = new Set<string>();
  const contactFrames = new Set<number>();
  if (!Number.isSafeInteger(frameCount) || frameCount <= 0)
    return {
      available: false as const,
      error: "Source frame range is unavailable.",
    };
  for (const event of doc.events) {
    if (
      typeof event.id !== "string" ||
      !event.id.trim() ||
      seen.has(event.id) ||
      typeof event.rally_id !== "string" ||
      !event.rally_id.trim() ||
      !Number.isSafeInteger(event.frame) ||
      event.frame < 0 ||
      event.frame >= frameCount ||
      !["shot", "serve", "rally_end"].includes(event.kind) ||
      (event.kind !== "rally_end" && contactFrames.has(event.frame))
    )
      return {
        available: false as const,
        error:
          "Annotation event identity or source frame is invalid. Reload valid annotations before using shot profiles.",
      };
    seen.add(event.id);
    if (event.kind !== "rally_end") contactFrames.add(event.frame);
  }
  const roster = doc.players.map((player, index) => ({
    key: `player:${JSON.stringify([player.id, index])}`,
    id: player.id,
    label: `${player.name || player.id} (${player.id})`,
    ambiguous:
      doc.players.filter((other) => other.id === player.id).length !== 1,
  }));
  const byId = new Map(
    roster.filter((p) => !p.ambiguous).map((p) => [p.id, p.key]),
  );
  const owner = (event: Event) =>
    byId.get(event.player_id ?? "") ?? "unresolved";
  const playerKey =
    hitter === "unresolved" || roster.some((p) => p.key === hitter)
      ? hitter
      : "all";
  const shots = doc.events.filter((event) => event.kind === "shot");
  const serves = doc.events.filter((event) => event.kind === "serve");
  const included = (event: Event) =>
    review === "all" || profileStatus(event) === "reviewed";
  const eligible = shots.filter(included);
  const eligibleServes = serves.filter(included);
  const selected = (event: Event) =>
    playerKey === "all" || owner(event) === playerKey;
  const events = eligible
    .filter(selected)
    .sort((a, b) => a.frame - b.frame || a.id.localeCompare(b.id));
  const family = (event: Event): Family =>
    profileFamilies.includes(event.family as Family)
      ? (event.family as Family)
      : "unknown";
  const side = (event: Event): Side =>
    profileSides.includes(event.side as Side)
      ? (event.side as Side)
      : "unknown";
  const families = profileFamilies.map((name) => {
    const members = events.filter((event) => family(event) === name);
    return {
      name,
      total: members.length,
      sides: Object.fromEntries(
        profileSides.map((s) => [
          s,
          members.filter((event) => side(event) === s).length,
        ]),
      ) as Record<Side, number>,
    };
  });
  const players = [
    ...roster,
    { key: "unresolved", id: "", label: "Unresolved hitter", ambiguous: false },
  ].map((player) => ({
    ...player,
    shots: eligible.filter((event) => owner(event) === player.key).length,
    serves: eligibleServes.filter((event) => owner(event) === player.key)
      .length,
  }));
  return {
    available: true as const,
    playerKey,
    players,
    families,
    events,
    recordedShots: shots.length,
    reviewedShots: shots.filter((event) => profileStatus(event) === "reviewed")
      .length,
    predictedShots: shots.filter(
      (event) => profileStatus(event) === "predicted",
    ).length,
    unknownStatusShots: shots.filter(
      (event) => profileStatus(event) === "unknown",
    ).length,
    eligibleShots: eligible.length,
    excludedShots: shots.length - eligible.length,
    unresolvedShots: eligible.filter((event) => owner(event) === "unresolved")
      .length,
    recordedServes: serves.length,
    selectedServes: eligibleServes.filter(selected).length,
    rallyEnds: doc.events.filter((event) => event.kind === "rally_end").length,
  };
}

export const ShotProfile = memo(function ShotProfile({
  doc,
  videoId,
  revision,
  dirty,
  saving,
  times,
  onSelect,
}: {
  doc: Document;
  videoId: string;
  revision: number;
  dirty: boolean;
  saving: boolean;
  times: number[];
  onSelect: (id: string) => void;
}) {
  const [review, setReview] = useState<ProfileReview>("reviewed");
  const [hitter, setHitter] = useState("all");
  const [page, setPage] = useState(0);
  const profile = useMemo(
    () => buildShotProfile(doc, times.length, review, hitter),
    [doc, times.length, review, hitter],
  );
  const count = profile.available ? profile.events.length : 0;
  const lastPage = Math.max(0, Math.ceil(count / 10) - 1);
  const currentPage = Math.min(page, lastPage);
  return (
    <details
      id="shot-profile"
      className="shot-profile"
      data-video={videoId}
      data-revision={revision}
    >
      <summary>Shot profiles</summary>
      <p id="shot-profile-snapshot">
        Source <code>{videoId}</code> · saved revision {revision} ·{" "}
        {saving
          ? "Saving; current draft"
          : dirty
            ? "Unsaved draft"
            : "Saved annotations"}
      </p>
      <p>
        Counts describe recorded annotations. Review status records an editing
        decision; it does not establish model accuracy or complete match
        coverage. JSON/CSV exports contain all saved events; these display
        filters do not change exports.
      </p>
      {!profile.available ? (
        <p role="alert">{profile.error}</p>
      ) : (
        <>
          <label htmlFor="shot-profile-review">
            Annotation filter
            <select
              id="shot-profile-review"
              value={review}
              onChange={(event) => {
                setReview(event.target.value as ProfileReview);
                setPage(0);
              }}
            >
              <option value="reviewed">Reviewed and corrected</option>
              <option value="all">
                All recorded shots (includes predictions)
              </option>
            </select>
          </label>
          <p id="shot-profile-coverage">
            {profile.recordedShots} recorded shots: {profile.reviewedShots}{" "}
            reviewed/corrected, {profile.predictedShots} predicted,{" "}
            {profile.unknownStatusShots} unknown review status.{" "}
            {profile.eligibleShots} included / {profile.excludedShots} excluded
            by this filter; {profile.unresolvedShots} included shots have
            unresolved hitters.
          </p>
          <div
            className="profile-table-wrap"
            tabIndex={0}
            role="region"
            aria-label="Shot counts by player"
          >
            <table>
              <caption>Players under the annotation filter</caption>
              <thead>
                <tr>
                  <th scope="col">Hitter</th>
                  <th scope="col">Shots</th>
                  <th scope="col">Serves</th>
                </tr>
              </thead>
              <tbody>
                {profile.players.map((player) => (
                  <tr
                    key={player.key}
                    data-profile-player={player.id || "unresolved"}
                  >
                    <th scope="row">
                      {player.label}
                      {player.ambiguous ? " · ambiguous roster ID" : ""}
                    </th>
                    <td>{player.shots}</td>
                    <td>{player.serves}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <label htmlFor="shot-profile-hitter">
            Detailed profile
            <select
              id="shot-profile-hitter"
              value={profile.playerKey}
              onChange={(event) => {
                setHitter(event.target.value);
                setPage(0);
              }}
            >
              <option value="all">All hitters</option>
              {profile.players.map((player) => (
                <option key={player.key} value={player.key}>
                  {player.label}
                  {player.ambiguous ? " · ambiguous roster ID" : ""}
                </option>
              ))}
            </select>
          </label>
          <p
            id="shot-profile-selection"
            data-shots={count}
            data-serves={profile.selectedServes}
          >
            {count} selected shots · {profile.selectedServes} selected serves (
            {profile.recordedServes} recorded). Serves and {profile.rallyEnds}{" "}
            recorded rally endings are separate from the shot grid.
          </p>
          <div
            className="profile-table-wrap"
            tabIndex={0}
            role="region"
            aria-label="Shot family and stroke side counts"
          >
            <table>
              <caption>Shot family × stroke side</caption>
              <thead>
                <tr>
                  <th scope="col">Family</th>
                  {profileSides.map((side) => (
                    <th key={side} scope="col">
                      {side === "unknown" ? "Unknown side" : pretty(side)}
                    </th>
                  ))}
                  <th scope="col">Total</th>
                </tr>
              </thead>
              <tbody>
                {profile.families.map((family) => (
                  <tr key={family.name} data-profile-family={family.name}>
                    <th scope="row">
                      {pretty(family.name)}
                      <span className="profile-bar" aria-hidden="true">
                        <span
                          style={{
                            width: `${count ? (100 * family.total) / count : 0}%`,
                          }}
                        />
                      </span>
                    </th>
                    {profileSides.map((side) => (
                      <td
                        key={side}
                        data-profile-cell={`${family.name}/${side}`}
                      >
                        {family.sides[side]}
                      </td>
                    ))}
                    <td>{family.total}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">Total</th>
                  {profileSides.map((side) => (
                    <td key={side}>
                      {profile.families.reduce(
                        (total, family) => total + family.sides[side],
                        0,
                      )}
                    </td>
                  ))}
                  <td>{count}</td>
                </tr>
              </tfoot>
            </table>
          </div>
          <p>
            Review contributing shots at their native source frames. Unknown
            family, side and hitter remain explicit.
          </p>
          {count ? (
            <>
              <ul id="shot-profile-events">
                {profile.events
                  .slice(currentPage * 10, currentPage * 10 + 10)
                  .map((event) => (
                    <li key={event.id}>
                      <button
                        type="button"
                        data-profile-jump={event.id}
                        onClick={() => onSelect(event.id)}
                      >
                        {clock(times[event.frame]!)} · frame {event.frame} ·{" "}
                        {pretty(event.family ?? "unknown")} /{" "}
                        {pretty(event.side ?? "unknown")} ·{" "}
                        {event.status ?? "unknown review status"}
                      </button>
                      <small>
                        {event.rally_id} ·{" "}
                        {profile.players.find(
                          (player) =>
                            player.id &&
                            player.id === event.player_id &&
                            !player.ambiguous,
                        )?.label ?? "Unresolved hitter"}
                        {event.contact_start_frame != null ||
                        event.contact_end_frame != null
                          ? ` · possible contact frames ${event.contact_start_frame ?? event.frame}–${event.contact_end_frame ?? event.frame}`
                          : ""}
                      </small>
                    </li>
                  ))}
              </ul>
              <div className="row profile-pagination">
                <button
                  id="shot-profile-previous"
                  type="button"
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                >
                  Previous shots
                </button>
                <span>
                  Page {currentPage + 1} of {lastPage + 1}
                </span>
                <button
                  id="shot-profile-next"
                  type="button"
                  disabled={currentPage === lastPage}
                  onClick={() => setPage(currentPage + 1)}
                >
                  Next shots
                </button>
              </div>
            </>
          ) : (
            <p id="shot-profile-empty">
              No recorded shots match these filters. Missing annotations do not
              establish that no shots occurred.
            </p>
          )}
        </>
      )}
    </details>
  );
});
