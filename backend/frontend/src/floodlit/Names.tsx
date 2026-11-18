import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client.js";
import { confirmNames, errorText, matchPlayers } from "./api.js";
import {
  initials,
  type MatchPlayers,
  type PersonId,
  type Team,
} from "./model.js";
import { go, useToast } from "./shell.js";

/** True when doubles partners entered together now stand on different sides. */
export function partnersSplit(
  players: { id: string; team: Team }[],
  assigned: Record<string, string>,
  teams: Record<string, string[]>,
) {
  return (["T1", "T2"] as const).some((team) => {
    const pair = teams[team] ?? [];
    if (pair.length < 2) return false;
    const sides = pair.map(
      (n) => players.find((p) => assigned[p.id] === n)?.team,
    );
    return sides[0] !== sides[1];
  });
}

export function Names({ id }: { id: string }) {
  const [data, setData] = useState<MatchPlayers | null>(null);
  const [assigned, setAssigned] = useState<Record<string, string>>({});
  const [picked, setPicked] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState<{
    text: string;
    notReady: boolean;
  } | null>(null);
  const [saving, setSaving] = useState(false);
  const focusId = useRef<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    const ctl = new AbortController();
    matchPlayers(id, ctl.signal).then(
      (d) => {
        setData(d);
        setAssigned(Object.fromEntries(d.players.map((p) => [p.id, p.name])));
      },
      (e) => {
        if (!ctl.signal.aborted)
          setLoadError({
            text: errorText(e),
            notReady: e instanceof ApiError && e.status === 409,
          });
      },
    );
    return () => ctl.abort();
  }, [id]);

  useEffect(() => {
    if (focusId.current)
      document
        .querySelector<HTMLElement>(`.person[data-id="${focusId.current}"]`)
        ?.focus();
    focusId.current = null;
  });

  if (loadError)
    return (
      <section className="page names" aria-labelledby="nm-title">
        <h1 id="nm-title" className="page-title">
          Who is who?
        </h1>
        <p className="lede page-lede">
          {loadError.notReady
            ? "The analysis has not found the players yet."
            : loadError.text}
        </p>
        <p className="page-actions">
          <a className="btn btn-flood" href={`#/match/${id}/processing`}>
            See the progress
          </a>
        </p>
      </section>
    );

  const people = data?.players ?? [];
  const split = data ? partnersSplit(people, assigned, data.teams) : false;

  function tap(pid: string) {
    focusId.current = pid;
    if (!picked) setPicked(pid);
    else if (picked === pid) setPicked(null);
    else {
      const a = assigned[picked] ?? "",
        b = assigned[pid] ?? "";
      setAssigned({ ...assigned, [picked]: b, [pid]: a });
      toast(`Swapped ${b} and ${a}`);
      setPicked(null);
    }
  }

  async function confirm() {
    setSaving(true);
    setError("");
    try {
      await confirmNames(id, assigned as Partial<Record<PersonId, string>>);
      go(`#/match/${id}/watch`);
    } catch (e) {
      setError(errorText(e));
      setSaving(false);
    }
  }

  return (
    <section className="page names" aria-labelledby="nm-title">
      <h1 id="nm-title" className="page-title">
        Who is who?
      </h1>
      <p className="lede">
        These are the people we followed, with the names we think fit. If two
        are the wrong way round, tap one and then the other to swap their names.
      </p>
      {!data ? (
        <p className="lede names-wait">Fetching the players…</p>
      ) : (
        <div className="lineup">
          {(["T1", "T2"] as const).map((team, k) => (
            <div key={team} style={{ display: "contents" }}>
              {k === 1 ? (
                <div className="lineup-net" aria-hidden="true"></div>
              ) : null}
              <div className={`lineup-side side-${k + 1}`}>
                <h2>Side {k + 1}</h2>
                <div className="lineup-row">
                  {people
                    .filter((p) => p.team === team)
                    .map((p) => (
                      <button
                        key={p.id}
                        className={`person${picked === p.id ? " picked" : ""}`}
                        data-id={p.id}
                        aria-pressed={picked === p.id}
                        onClick={() => tap(p.id)}
                      >
                        <span className="person-photo">
                          {p.thumbnail_url ? (
                            <img src={p.thumbnail_url} alt="" />
                          ) : (
                            <span className="person-none">
                              {initials(assigned[p.id] ?? p.id)}
                            </span>
                          )}
                        </span>
                        <span className="person-name">{assigned[p.id]}</span>
                        <span className="person-hint">
                          {picked === p.id
                            ? "Now tap who to swap with"
                            : picked
                              ? "Swap with this person"
                              : "Tap to swap"}
                        </span>
                      </button>
                    ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      <p className="form-error" role="alert">
        {split
          ? "Partners you entered together are now on different sides. Swap them back so each pair stands together."
          : error}
      </p>
      <div className="names-actions">
        <button
          className="btn btn-flood"
          onClick={confirm}
          disabled={!data || split || saving}
        >
          {saving ? "Saving…" : "Names look right"}
        </button>
      </div>
    </section>
  );
}
