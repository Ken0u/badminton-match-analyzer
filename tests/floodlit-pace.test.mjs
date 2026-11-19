// Run: node --test tests/floodlit-pace.test.mjs (no browser or local match needed).
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.location = {search: ''};
const source = await readFile(new URL('../design/prototypes/a-floodlit/js/data.js', import.meta.url));
const {estimatePace,estimateBow,speedOf} = await import(`data:text/javascript;base64,${source.toString('base64')}`);
function fixture() {
  const xs = Array.from({length: 21}, (_, k) => 0.7 - 0.3*Math.expm1(-3*k/20)/Math.expm1(-3));
  const m = {analysis:{video:{frame_count:21,width:1280,fps:25},tracks:{shuttle:{x:xs}}},views:[{start_frame:0,end_frame:21,inverse:[[1,0,0],[0,1,0],[0,0,1]]}]};
  const shot = k => ({frame:k,time_s:k/25,shuttle:{x:xs[k]},hitter_position:{x:1,y:2}});
  return [m,shot(0),shot(20),1.3];
}
test('recovers pace despite missing and false detections',()=>{
  const args=fixture(), xs=args[0].analysis.tracks.shuttle.x;
  xs[3]=null; xs[7]=0.99;
  assert.equal(estimatePace(...args),3);
});
test('uses prior across cuts, sparse tracks or insufficient sideways motion',()=>{
  for(const change of [a=>a[0].views[0].end_frame=20,a=>a[0].analysis.tracks.shuttle.x.fill(null),a=>a[2].shuttle.x=0.69]) {
    const args=fixture();change(args);assert.equal(estimatePace(...args),null);
  }
});

test('recovers a known vertical arc and ignores missing height evidence',()=>{
  const [m,a,b]=fixture(); m.views[0].inverse[0][0]=0.06;
  a.shuttle.y=b.shuttle.y=0.5;m.analysis.video.height=720;
  const ys=m.analysis.tracks.shuttle.y=Array.from({length:21},(_,k)=>{
    const u=Math.expm1(-1.3*k/20)/Math.expm1(-1.3);
    return 0.5-4*0.06*1280/720*u*(1-u);
  });
  assert.ok(Math.abs(estimateBow(m,a,b,1.3,2)-4)<1e-8);
  ys.fill(null);assert.equal(estimateBow(m,a,b,1.3,2),2);
});

test('bounded launch is never shown as a number, whatever the diagnostics',()=>{
  const f={quality:'speed_bound',initial_speed_kmh:450,speed_settled_kmh:119.8};
  assert.deepEqual(speedOf({flight:f}),{bound:true});
  assert.deepEqual(speedOf({flight:{...f,settled_supported:true}}),{bound:true});
  assert.equal(speedOf({flight:{...f,quality:'poor_fit',settled_supported:true}}),null);
});

test('a good fit shows its fitted launch speed; launch diagnostics never hide or replace it',()=>{
  const f={quality:'good',initial_speed_kmh:81,early_speed_kmh:82.3,launch_supported:true};
  assert.deepEqual(speedOf({flight:f}),{kmh:81});
  assert.deepEqual(speedOf({flight:{...f,launch_supported:false}}),{kmh:81});
  assert.deepEqual(speedOf({flight:{...f,launch_supported:false,settled_supported:true,speed_settled_kmh:54}}),{kmh:81});
});
