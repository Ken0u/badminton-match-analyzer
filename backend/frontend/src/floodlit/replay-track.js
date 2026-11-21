// Presentation-only samples. Never write inferred coverage into match tracks.
const finite = p => Number.isFinite(p?.x) && Number.isFinite(p?.y);
const read = (track, k) => {
  const p = { x: track?.x[k], y: track?.y[k] };
  return finite(p) ? p : null;
};
const clamp = (v, lo, hi) => Math.max(lo, Math.min(v, hi));
// A contact snapshot can identify which avatar should perform a stroke even
// when tracking did not preserve the hitter ID. Never publish this staging
// choice as an annotation; incomplete/ambiguous snapshots stay unassigned.
export function replayActor(shot, roster) {
  if (shot.hitter_id != null) return shot.hitter_id;
  const at = shot.hitter_position, rows = shot.players;
  if (!finite(at) || !Array.isArray(rows)) return null;
  const contacts = rows.filter(p => finite(p.position) && p.position.x === at.x && p.position.y === at.y);
  if (contacts.length !== 1) return null;
  const ids = new Set(roster.map(p => p.id)), hit = contacts[0];
  if (hit.person_id != null) return ids.has(hit.person_id) ? hit.person_id : null;
  if (ids.size !== roster.length || rows.length !== ids.size) return null;
  for (const row of rows) {
    if (row !== hit && (!finite(row.position) || !ids.delete(row.person_id))) return null;
  }
  return ids.size === 1 ? ids.values().next().value : null;
}
export function replaySamples(match, id, first, last, shots, fallback) {
  const hz = match.analysis.tracks.rate_hz, tr = match.trackIndex.get(id);
  const points = Array.from({length: last-first+1}, (_, i) => read(tr, first+i));
  for (const shot of shots) {
    const i = Math.round(shot.time_s*hz)-first;
    if (i >= 0 && i < points.length && !points[i] && shot.hitter_id === id && finite(shot.hitter_position))
      points[i] = { ...shot.hitter_position };
  }
  const roster = match.analysis.players, team = roster.find(p => p.id === id)?.team;
  const mates = team ? roster.filter(p => p.team === team && p.id !== id) : [];
  const mate = mates.length === 1 ? match.trackIndex.get(mates[0].id) : undefined;
  // Only stage rear coverage when a paired observation places this player
  // clearly behind their partner on the same court end. Do not invent hits.
  const rear = i => {
    const p = points[i], m = read(mate, first+i);
    return p && m && (p.y-6.7)*(m.y-6.7)>0 && Math.abs(p.y-6.7)>Math.abs(m.y-6.7)+0.8;
  };
  for (let i=0; i<points.length;) {
    if (points[i]) { i++; continue; }
    const begin=i; while (i<points.length && !points[i]) i++;
    const l=begin-1, r=i, left=points[l], right=points[r];
    const cover = (r-begin)/hz >= 0.8 && (left || right) && (!left || rear(l)) && (!right || rear(r));
    for (let j=begin; j<r; j++) {
      const a=left || right || fallback, b=right || a, u=left && right ? (j-l)/(r-l) : 0;
      let x=a.x+(b.x-a.x)*u, y=a.y+(b.y-a.y)*u;
      const m=cover && read(mate, first+j);
      if (m && (m.y-6.7)*(y-6.7)>0) {
        // Keep the back player behind play, shading toward the partner's
        // channel. Fade into both real samples (including shot anchors).
        const fade=clamp(Math.min(left ? j-l : Infinity, right ? r-j : Infinity)/(0.45*hz),0,1);
        x+=fade*clamp(0.60*(m.x-x),-1.5,1.5);
        const target=clamp(m.y+Math.sign(y-6.7)*2.2,0.3,13.1);
        y+=fade*clamp(target-y,-0.9,0.9);
      }
      points[j]={x,y};
    }
  }
  return points;
}
