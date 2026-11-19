"""Camera from the court, and a 3D shuttle flight fitted to the image track.

The court detector gives a floor homography per camera view (normalized
image point -> court metres). With square pixels and the principal point at
the picture centre, that homography fixes a full pinhole camera: a focal
length, a rotation and a position (``camera_from_homography``). The two
camera has one degree of freedom fewer than the homography, so the camera
cannot always reproduce it exactly; the leftover is reported as
``Camera.reprojection`` (image heights, over a grid of court points).

Between two contacts the shuttle flies under gravity and quadratic air drag,
``a = -g z - (g / vt^2) |v| v`` with a terminal velocity ``vt`` of about
6.7 m/s. ``fit_flight`` finds the start point and velocity whose projection
best follows the shuttle's image track (robust least squares, numpy only),
with weak priors that the shot starts near the hitter at a racket height.
Integrating the fitted flight forward gives where it reaches the floor or
the net, the initial speed and the landing speed and angle. The fit's
covariance, carried to the landing point, is the landing's uncertainty
(``sigma_m``), which callers use to decide whether to trust it.

Court frame as in MatchAnalysis: x 0..6.1 across, y 0..13.4 from the far
baseline, net at y = 6.7; heights z in metres above the floor.
"""

import math
from dataclasses import dataclass

import numpy as np

GRAVITY = 9.81
TERMINAL_VELOCITY = 6.7
NET_Y = 6.7
NET_HEIGHT = 1.53  # 1.524 at the centre, 1.55 at the posts
STEP_S = 1 / 60
# Image residual scale (image heights): about 3 pixels at 720p.
SIGMA_IMAGE = 0.004
# Priors on the start of a shot: within about a metre of the hitter's feet,
# at a racket height.
SIGMA_HITTER_M = 1.0
START_HEIGHT_M = 1.9
SIGMA_START_HEIGHT_M = 0.9
MAX_SPEED_M_S = 125.0
# The flight may not be under the floor at an observation; with ``grounded``
# the last observation is the shuttle on the floor.
SIGMA_FLOOR_M = 0.03
SIGMA_GROUNDED_M = 0.1
# Robust (Cauchy) scales of the image residual, image heights: a wide one to
# find the flight, then narrower ones to settle on it.
ROBUST_SCALES = (0.03, 0.015, 0.01)
MIN_POINTS = 5
SETTLED_S = 0.1


# Camera ---------------------------------------------------------------------


@dataclass
class Camera:
    """Pinhole camera: ``camera = R @ world + t``; world z is up.

    ``focal`` is in image heights; image points are normalized (0..1 of
    width and height) as everywhere in the app.
    """

    focal: float
    rotation: np.ndarray
    translation: np.ndarray
    aspect: float
    reprojection: float = 0.0

    @property
    def centre(self):
        return -self.rotation.T @ self.translation

    def project(self, points):
        """World points [..., 3] to (normalized image [..., 2], depth [...])."""
        p = np.asarray(points, float) @ self.rotation.T + self.translation
        depth = p[..., 2]
        safe = np.where(np.abs(depth) < 1e-9, 1e-9, depth)
        x = self.focal * p[..., 0] / safe / self.aspect + 0.5
        y = self.focal * p[..., 1] / safe + 0.5
        return np.stack([x, y], -1), depth

    def ray(self, u, v):
        """(origin, unit direction) in the world through image point (u, v)."""
        d = np.array([(u - 0.5) * self.aspect / self.focal, (v - 0.5) / self.focal, 1])
        d = self.rotation.T @ d
        return self.centre, d / np.linalg.norm(d)

    def at_height(self, u, v, height):
        """World point on the ray through (u, v) at this height, or None."""
        origin, d = self.ray(u, v)
        if abs(d[2]) < 1e-9:
            return None
        s = (height - origin[2]) / d[2]
        return None if s <= 0 else origin + s * d

    def describe(self):
        c = self.centre
        return {
            "focal": round(float(self.focal), 4),
            "vertical_fov_deg": round(math.degrees(2 * math.atan(0.5 / self.focal)), 2),
            "centre_m": [round(float(v), 2) for v in c],
            "reprojection": round(float(self.reprojection), 6),
        }


def _rotation(vector):
    """Rodrigues: axis-angle [3] -> rotation matrix."""
    theta = float(np.linalg.norm(vector))
    if theta < 1e-12:
        return np.eye(3)
    k = vector / theta
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(theta) * kx + (1 - math.cos(theta)) * kx @ kx


def _axis_angle(matrix):
    angle = math.acos(max(-1.0, min(1.0, (np.trace(matrix) - 1) / 2)))
    if angle < 1e-9:
        return np.zeros(3)
    v = np.array(
        [
            matrix[2, 1] - matrix[1, 2],
            matrix[0, 2] - matrix[2, 0],
            matrix[1, 0] - matrix[0, 1],
        ]
    )
    return v * angle / (2 * math.sin(angle))


GRID = np.array(
    [(x, y) for x in np.linspace(0, 6.1, 5) for y in np.linspace(0, 13.4, 7)], float
)


def camera_from_homography(matrix, aspect):
    """The camera behind a floor homography (normalized image -> court).

    Closed form (Zhang's two constraints with one unknown focal length),
    then refined so the camera reprojects the homography's court grid.
    Returns None when no camera fits (no positive focal length).
    """
    h = np.asarray(matrix, float)
    if h.shape != (3, 3) or not np.isfinite(h).all():
        return None
    try:
        g = np.linalg.inv(h)
    except np.linalg.LinAlgError:
        return None
    centred = np.array([[aspect, 0, -aspect / 2], [0, 1, -0.5], [0, 0, 1]])
    g = centred @ g
    g = g / np.linalg.norm(g[:, :2])
    (a1, b1, c1), (a2, b2, c2) = g[:, 0], g[:, 1]
    alpha = np.array([a1 * a2 + b1 * b2, a1**2 + b1**2 - a2**2 - b2**2])
    beta = np.array([c1 * c2, c1**2 - c2**2])
    w = -(alpha @ beta) / max(alpha @ alpha, 1e-18)
    if not w > 0:
        return None
    focal = 1 / math.sqrt(w)
    k_inv = np.diag([1 / focal, 1 / focal, 1.0])
    m = k_inv @ g
    scale = 2 / (np.linalg.norm(m[:, 0]) + np.linalg.norm(m[:, 1]))
    if (scale * m[:, 2])[2] < 0:
        scale = -scale
    r1, r2, t = scale * m[:, 0], scale * m[:, 1], scale * m[:, 2]
    n = np.cross(r1, r2)
    # World z is up: the camera centre must be above the floor.
    r3 = -n if n @ t > 0 else n
    u, _, vt = np.linalg.svd(np.stack([r1, r2, r3], 1))
    rotation = u @ vt
    if np.linalg.det(rotation) * np.linalg.det(np.stack([r1, r2, r3], 1)) < 0:
        rotation = u @ np.diag([1, 1, -1]) @ vt
    # The world frame (x right, y towards the camera, z up) is left-handed:
    # keep the reflection in the rotation, refine a proper rotation times it.
    flip = np.diag([1.0, 1.0, np.sign(np.linalg.det(rotation))])
    proper = rotation @ flip
    target = np.stack([_homography_image(h, p) for p in GRID])
    if not np.isfinite(target).all():
        return None
    world = np.column_stack([GRID, np.zeros(len(GRID))])

    def residuals(params):
        rot = _rotation(params[1:4]) @ flip
        cam = Camera(params[0], rot, params[4:7], aspect)
        image, depth = cam.project(world)
        out = (image - target) * [aspect, 1]
        return np.concatenate([out.ravel(), np.minimum(depth, 0) * 10])

    start = np.concatenate([[focal], _axis_angle(proper), t])
    params = _lm(residuals, start, iterations=30)
    rot = _rotation(params[1:4]) @ flip
    if not params[0] > 0:
        return None
    camera = Camera(float(params[0]), rot, params[4:7].copy(), aspect)
    camera.reprojection = float(np.sqrt(np.mean(residuals(params)[: -len(GRID)] ** 2)))
    if camera.centre[2] <= 0:
        return None
    return camera


def _homography_image(h, point):
    """Court point -> normalized image point through the inverse homography."""
    p = np.linalg.solve(h, np.array([point[0], point[1], 1.0]))
    return p[:2] / p[2]


def _lm(fun, x0, iterations=30, lam=1e-3):
    """Plain Levenberg-Marquardt with a forward-difference Jacobian."""
    x = np.asarray(x0, float).copy()
    r = fun(x)
    cost = r @ r
    for _ in range(iterations):
        eps = 1e-6 * np.maximum(1, np.abs(x))
        jac = np.stack([(fun(x + e) - r) / e[k] for k, e in enumerate(np.diag(eps))], 1)
        a, b = jac.T @ jac, jac.T @ r
        improved = False
        for _ in range(8):
            try:
                step = np.linalg.solve(a + lam * np.diag(np.diag(a) + 1e-12), -b)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            trial = fun(x + step)
            if trial @ trial < cost:
                x, r, cost = x + step, trial, trial @ trial
                lam = max(lam / 3, 1e-9)
                improved = True
                break
            lam *= 10
        if not improved or np.abs(step).max() < 1e-9:
            break
    return x


# Flight ---------------------------------------------------------------------


def _acceleration(v, vt):
    speed = np.sqrt((v * v).sum(-1))[..., None]
    a = v * (speed * -(GRAVITY / vt**2))
    a[..., 2] -= GRAVITY
    return a


def integrate(state, duration, vt=None, step=None):
    """RK4 of states [B, 6] (position, velocity) over [0, duration].

    Returns (times [N], positions [N, B, 3], velocities [N, B, 3]).
    """
    vt = TERMINAL_VELOCITY if vt is None else vt
    step = STEP_S if step is None else step
    state = np.atleast_2d(np.asarray(state, float))
    count = max(1, math.ceil(duration / step))
    out = np.empty((count + 1, *state.shape))
    out[0] = y = state
    k = -(GRAVITY / vt**2)
    half, sixth = 0.5 * step, step / 6

    def rate(y):
        v = y[:, 3:]
        d = np.empty_like(y)
        d[:, :3] = v
        d[:, 3:] = v * (np.sqrt((v * v).sum(1)) * k)[:, None]
        d[:, 5] -= GRAVITY
        return d

    for n in range(count):
        k1 = rate(y)
        k2 = rate(y + half * k1)
        k3 = rate(y + half * k2)
        k4 = rate(y + step * k3)
        y = y + sixth * (k1 + 2 * (k2 + k3) + k4)
        out[n + 1] = y
    return np.arange(count + 1) * step, out[:, :, :3], out[:, :, 3:]


def positions_at(state, at, vt=None, step=None):
    """Positions [B, len(at), 3] of the flights from ``state`` at times ``at``."""
    at = np.asarray(at, float)
    step = STEP_S if step is None else step
    grid, ps, vs = integrate(state, float(at.max()) + step, vt, step)
    k = np.clip((at // step).astype(int), 0, len(grid) - 2)
    s = ((at - grid[k]) / step)[None, :, None]
    p0, p1 = ps[k].transpose(1, 0, 2), ps[k + 1].transpose(1, 0, 2)
    v0, v1 = vs[k].transpose(1, 0, 2) * step, vs[k + 1].transpose(1, 0, 2) * step
    # Cubic Hermite between grid points.
    h00, h10 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s
    h01, h11 = -2 * s**3 + 3 * s**2, s**3 - s**2
    return h00 * p0 + h10 * v0 + h01 * p1 + h11 * v1


def early_track_speed(camera, state, at, observed, inliers, *, resolved_clock=False):
    """Conditional launch estimate from timed early displacements, in km/h.

    Keep the full-flight depth, start point and direction. Compare drag-aware
    candidate speeds in the original camera rather than turning pixels into
    metres with a constant scale. Missing contact frames cannot fix launch
    speed. These gates measure local observability, not radar accuracy.
    """
    at = np.asarray(at)
    use = np.asarray(inliers) & (at >= 0) & (at <= 0.16)
    t, obs = at[use], np.asarray(observed)[use]
    first_limit = 0.035 if resolved_clock else 0.02
    if len(t) < 4 or t[0] > first_limit or t[1] > 0.06 or t[-1] < 0.08:
        return None
    # Keep the calculation bounded for high-rate video.
    if len(t) > 16:
        keep = np.linspace(0, len(t) - 1, 16).round().astype(int)
        t, obs = t[keep], obs[keep]
    i, j = np.triu_indices(len(t), 1)
    keep = (t[j] - t[i] >= 0.035) & (t[j] - t[i] <= 0.125)
    i, j = i[keep], j[keep]
    if len(i) < 3:
        return None
    scales = np.linspace(0.70, 1.30, 31)
    states = np.tile(state, (len(scales), 1)).astype(float)
    states[:, 3:] *= scales[:, None]
    uv, depth = camera.project(positions_at(states, t))
    if np.any(depth <= 0) or not np.isfinite(uv).all():
        return None
    delta = (uv[:, j] - uv[:, i]) * [camera.aspect, 1]
    measured = (obs[j] - obs[i]) * [camera.aspect, 1]

    def norm(x):
        return np.linalg.norm(x, axis=-1)

    # Can a +/-10% change in launch speed be distinguished above image noise?
    sensitive = norm(delta[20] - delta[10]) >= 2 * SIGMA_IMAGE
    if resolved_clock:
        # Late pairs contain little launch information after rapid deceleration.
        # Use informative baselines only, with at least two distinct anchors
        # so a single noisy first detection cannot determine the speed.
        if sensitive.sum() < 3 or len(np.unique(i[sensitive])) < 2:
            return None
        delta, measured = delta[:, sensitive], measured[sensitive]
    elif np.median(norm(delta[20] - delta[10])) < 2 * SIGMA_IMAGE:
        return None
    residual = norm(delta - measured)
    score = np.median(residual, axis=1)
    # A small preference for the global estimate resists chasing detector jitter.
    k = int(np.argmin(score + SIGMA_IMAGE * np.abs(scales - 1)))
    if k in (0, len(scales) - 1) or score[k] > 2 * SIGMA_IMAGE:
        return None
    speed = float(np.linalg.norm(states[k, 3:]) * 3.6)
    return speed if 0 < speed < 440 else None


# A conservative triage band, not a confidence interval or a tape-call rule.
NET_REVIEW_MARGIN_M = 0.10


def continuing_net_check(state, duration):
    """Check a single fitted centre trajectory only up to the next contact.

    None means unassessed, not clear. Use the across-court coordinate at the
    crossing to exclude round-the-post paths. Never infer a rally outcome.
    """
    if not math.isfinite(duration) or duration <= 0:
        return None
    grid, positions, _ = integrate(state, duration)
    points = positions[:, 0]
    for i in np.flatnonzero(np.diff(points[:, 1]) != 0):
        a, b = points[i], points[i + 1]
        u = (NET_Y - a[1]) / (b[1] - a[1])
        if not 0 <= u <= 1 or grid[i] + u * (grid[i + 1] - grid[i]) > duration:
            continue
        x, _, height = a + u * (b - a)
        if not (0 <= x <= 6.1 and math.isfinite(height)):
            return None
        clearance = float(height - NET_HEIGHT)
        status = "near_tape"
        if clearance < -NET_REVIEW_MARGIN_M:
            status = "below_net"
        elif clearance > NET_REVIEW_MARGIN_M:
            status = "clear"
        return {"net_check": status, "net_clearance_m": round(clearance, 4)}
    return None


def touchdown(state, vt=None, limit_s=4.0, net_after_s=0.0, step=None):
    """Where flights [B, 6] first meet the floor or the net.

    Returns a list of dicts (or None when a flight stays up for limit_s):
    {"time_s", "point" [x, y, z], "velocity", "net"}. A flight crossing the
    net plane below the tape later than ``net_after_s`` (None: never) stops
    there (``net`` true); before it, the shuttle was seen flying on, so it
    went over.
    """
    step = STEP_S if step is None else step
    grid, ps, vs = integrate(state, limit_s, vt, step)
    out = []
    for b in range(ps.shape[1]):
        p, v = ps[:, b], vs[:, b]
        found = None
        side = np.sign(p[:, 1] - NET_Y)
        for n in range(1, len(grid)):
            crossing = side[n] != side[n - 1] and side[n - 1] != 0
            if net_after_s is not None and crossing and grid[n] > net_after_s:
                f = (NET_Y - p[n - 1, 1]) / (p[n, 1] - p[n - 1, 1])
                q = p[n - 1] + f * (p[n] - p[n - 1])
                if 0 <= q[2] < NET_HEIGHT:
                    found = (
                        grid[n - 1] + f * step,
                        q,
                        v[n - 1] + f * (v[n] - v[n - 1]),
                        True,
                    )
                    break
            if p[n, 2] <= 0 < p[n - 1, 2] or (n == 1 and p[0, 2] <= 0):
                f = p[n - 1, 2] / max(p[n - 1, 2] - p[n, 2], 1e-12)
                f = min(max(f, 0.0), 1.0)
                q = p[n - 1] + f * (p[n] - p[n - 1])
                found = (
                    grid[n - 1] + f * step,
                    q,
                    v[n - 1] + f * (v[n] - v[n - 1]),
                    False,
                )
                break
        if found is None:
            out.append(None)
            continue
        t, q, vel, hit_net = found
        out.append(
            {
                "time_s": float(t),
                "point": q.tolist(),
                "velocity": vel.tolist(),
                "net": hit_net,
            }
        )
    return out


def _residuals(
    params, camera, at, observed, hitter, weights, grounded=False, reception=None
):
    """Image residuals [B, 2N] (scaled by SIGMA_IMAGE), the flight staying
    above the floor at every observation [B, N], and the priors."""
    params = np.atleast_2d(params)
    pos = positions_at(params, at)
    under = np.minimum(pos[..., 2], 0) / SIGMA_FLOOR_M
    image, depth = camera.project(pos)
    r = (image - observed[None]) * [camera.aspect, 1] / SIGMA_IMAGE
    r = r * np.sqrt(weights)[None, :, None]
    r = np.concatenate([r.reshape(len(params), -1), under], 1)
    behind = np.minimum(depth, 0.5).reshape(len(params), -1) - 0.5
    priors = [
        (params[:, 2] - START_HEIGHT_M) / SIGMA_START_HEIGHT_M,
        np.minimum(params[:, 2] - 0.05, 0) * 50,
        np.maximum(np.linalg.norm(params[:, 3:], axis=1) - MAX_SPEED_M_S, 0),
        behind.min(1) * 20,
    ]
    if hitter is not None:
        priors += [
            (params[:, 0] - hitter[0]) / SIGMA_HITTER_M,
            (params[:, 1] - hitter[1]) / SIGMA_HITTER_M,
        ]
    if reception is not None:
        # Only for a continuing, opposed exchange with observed endpoints.
        # Feet are not racket contact: keep this a weak horizontal prior.
        feet, duration = reception
        grid, ps, _ = integrate(params, duration)
        end = positions_at(params, np.array([duration]))[:, 0]
        priors.extend((end[:, k] - feet[k]) / SIGMA_HITTER_M for k in (0, 1))
        # Smooth (unrounded) crossing residual in either playing direction.
        # No crossing or round-the-post is not evidence of an under-tape shot.
        a, b = ps[:-1], ps[1:]
        dy = b[..., 1] - a[..., 1]
        u = (NET_Y - a[..., 1]) / np.where(dy != 0, dy, 1)
        valid = (
            (dy != 0) & (u >= 0) & (u <= 1) & (grid[:-1, None] + u * STEP_S <= duration)
        )
        cross = a + u[..., None] * (b - a)
        valid &= (cross[..., 0] >= 0) & (cross[..., 0] <= 6.1)
        priors.append(
            np.where(valid, np.minimum(cross[..., 2] - NET_HEIGHT, 0), 0).min(axis=0)
            / 0.025
        )
    if grounded:
        priors.append(pos[:, -1, 2] / SIGMA_GROUNDED_M)
    return np.concatenate([r, np.stack(priors, 1)], 1)


def _start_guesses(camera, first, hitter, towards):
    """Candidate start states: the hitter's spot (or the first image point at
    racket height), velocities over a grid of directions and speeds."""
    starts = []
    if hitter is not None:
        starts.append(np.array([hitter[0], hitter[1], START_HEIGHT_M]))
    if first is not None:
        p = camera.at_height(first[0], first[1], START_HEIGHT_M)
        if p is not None and abs(p[0]) < 20 and abs(p[1]) < 30:
            starts.append(p)
    if not starts:
        starts.append(np.array([3.05, 3.0 if towards > 0 else 10.4, START_HEIGHT_M]))
    states = []
    for start in starts:
        for heading in np.radians([-40, -20, -8, 0, 8, 20, 40]):
            for elevation in np.radians([-25, -8, 5, 20, 40, 60]):
                for speed in (8.0, 18.0, 35.0, 70.0):
                    d = np.array(
                        [
                            math.sin(heading) * math.cos(elevation),
                            towards * math.cos(heading) * math.cos(elevation),
                            math.sin(elevation),
                        ]
                    )
                    states.append(np.concatenate([start, speed * d]))
    return np.array(states)


def _bounded(params):
    """Parameters kept where the integration is meaningful."""
    out = np.array(params, float)
    out[:2] = np.clip(out[:2], -30, 45)
    out[2] = np.clip(out[2], -1, 8)
    speed = np.linalg.norm(out[3:])
    if speed > 2 * MAX_SPEED_M_S:
        out[3:] *= 2 * MAX_SPEED_M_S / speed
    return out


def _batched_lm(
    camera,
    at,
    observed,
    hitter,
    weights,
    x0,
    iterations=15,
    grounded=False,
    reception=None,
):
    """Levenberg-Marquardt, one integration per iteration.

    Each iteration integrates, in one batch, four damped trial steps and
    every trial's finite-difference neighbours, so the accepted trial brings
    its own Jacobian. Returns (parameters, cost, Jacobian at them).
    """
    eps = np.array([1e-4, 1e-4, 1e-4, 1e-3, 1e-3, 1e-3])

    def evaluate(points):
        batch = np.vstack(
            [np.vstack([p[None], p[None] + np.diag(eps)]) for p in points]
        )
        rs = _residuals(
            batch, camera, at, observed, hitter, weights, grounded, reception
        )
        rs = rs.reshape(len(points), 7, -1)
        jacs = ((rs[:, 1:] - rs[:, :1]) / eps[None, :, None]).transpose(0, 2, 1)
        return rs[:, 0], jacs

    x = np.asarray(x0, float).copy()
    rs, jacs = evaluate([x])
    r, jac = rs[0], jacs[0]
    c = float(r @ r)
    lam = 1e-2
    for _ in range(iterations):
        a, b = jac.T @ jac, jac.T @ r
        steps = []
        for scale in (lam / 10, lam, lam * 10, lam * 100):
            try:
                steps.append(
                    np.linalg.solve(a + scale * np.diag(np.diag(a) + 1e-9), -b)
                )
            except np.linalg.LinAlgError:
                continue
        if not steps:
            break
        rs, jacs = evaluate([_bounded(x + s) for s in steps])
        costs = (rs**2).sum(1)
        costs = np.where(np.isfinite(costs), costs, np.inf)
        best = int(np.argmin(costs))
        if costs[best] >= c:
            lam *= 1000
            if lam > 1e8:
                break
            continue
        x, r, jac, c = (
            _bounded(x + steps[best]),
            rs[best],
            jacs[best],
            float(costs[best]),
        )
        lam = max(lam / 10 if best == 0 else lam if best == 1 else lam * 10, 1e-7)
        if np.abs(steps[best]).max() < 1e-5 or c < 1e-12:
            break
    return x, c, jac


def fit_flight(
    camera,
    at,
    observed,
    hitter=None,
    towards=None,
    iterations=2,
    grounded=False,
    reception=None,
    resolved_clock=False,
):
    """Fit one shot's flight to its image track.

    ``at`` are seconds after the contact of the observed normalized image
    points ``observed`` [N, 2]; ``hitter`` the hitter's feet (court metres)
    or None; ``towards`` +1 when the shot goes towards the near end (y
    growing), -1 towards the far end, None when unknown (both are tried).
    Robust: points far off the fitted flight are down-weighted (Cauchy),
    re-fitted ``iterations`` times.

    Returns None with fewer than MIN_POINTS points, else a dict with the
    start state, "rms" (image heights, inliers), "inliers", "touchdown"
    (see ``touchdown``), "sigma_m" (landing standard deviation in metres from
    the fit covariance), speeds and the observed span.
    """
    at = np.asarray(at, float)
    observed = np.asarray(observed, float)
    if len(at) < MIN_POINTS:
        return None
    order = np.argsort(at)
    at, observed = at[order], observed[order]
    first = observed[0] if at[0] <= 0.1 else None
    directions = [towards] if towards in (1, -1) else [1, -1]
    guesses = np.vstack([_start_guesses(camera, first, hitter, d) for d in directions])
    n = 2 * len(at)

    def errors(x):
        image, _ = camera.project(positions_at(x[None], at)[0])
        return np.linalg.norm((image - observed) * [camera.aspect, 1], axis=1)

    def robust(r, scale):
        # Cauchy cost of the image residuals (in SIGMA_IMAGE units) plus priors.
        k = scale / SIGMA_IMAGE
        image = r[:, :n].reshape(len(r), -1, 2)
        return np.log1p((image**2).sum(2) / k**2).sum(1) * k**2 + (r[:, n:] ** 2).sum(1)

    weights = np.ones(len(at))
    r = _residuals(guesses, camera, at, observed, hitter, weights, grounded)
    scores = robust(r, ROBUST_SCALES[0])
    best = []
    for index in np.argsort(scores)[:3]:
        x = guesses[index]
        for scale in ROBUST_SCALES[:1]:
            weights = 1 / (1 + (errors(x) / scale) ** 2)
            x, _, _ = _batched_lm(
                camera, at, observed, hitter, weights, x, grounded=grounded
            )
        r = _residuals(x, camera, at, observed, hitter, np.ones(len(at)), grounded)
        best.append((float(robust(r, ROBUST_SCALES[0])[0]), x))
    _, x = min(best, key=lambda item: item[0])
    for scale in ROBUST_SCALES[1 : 1 + iterations]:
        weights = 1 / (1 + (errors(x) / scale) ** 2)
        x, _, jac = _batched_lm(camera, at, observed, hitter, weights, x, 10, grounded)
    err = errors(x)
    initially_capped = np.linalg.norm(x[3:]) * 3.6 >= 440.0
    if reception is not None and not grounded and len(at) >= 7:
        feet, duration = reception
        before = continuing_net_check(x, duration)
        low = before is not None and before["net_clearance_m"] < 0
        if (
            (low or initially_capped)
            and 0 <= duration - at[-1] <= 0.10
            and at[0] <= 0.10
        ):
            w = 1 / (1 + (err / ROBUST_SCALES[-1]) ** 2)
            trial, _, trial_jac = _batched_lm(
                camera, at, observed, hitter, w, x, reception=reception
            )
            after = continuing_net_check(trial, duration)
            trial_err = errors(trial)

            # Compare the SAME detections (including outliers). Don't trade a
            # worse image fit or a vanished crossing for a plausible speed.
            def receiver_distance(state):
                return np.linalg.norm(
                    positions_at(state[None], [duration])[0, 0, :2] - feet
                )

            if (
                after is not None
                and before is not None
                and after["net_clearance_m"] >= min(0, before["net_clearance_m"])
                and (not low or after["net_clearance_m"] > before["net_clearance_m"])
                and (low or np.linalg.norm(trial[3:]) < np.linalg.norm(x[3:]))
                and receiver_distance(trial) < receiver_distance(x)
                and np.sum(trial_err <= 3 * SIGMA_IMAGE)
                >= np.sum(err <= 3 * SIGMA_IMAGE)
                and np.sqrt(np.mean(trial_err**2)) <= np.sqrt(np.mean(err**2)) + 0.001
            ):
                x, jac, err = trial, trial_jac, trial_err
    inliers = err <= 3 * SIGMA_IMAGE
    rms = (
        float(np.sqrt(np.mean(err[inliers] ** 2)))
        if inliers.any()
        else float(err.mean())
    )
    down = touchdown(x[None], net_after_s=float(at[-1]))[0]
    sigma = None
    if down is not None:
        # Landing covariance: (J^T J)^-1 with the residual scale, carried to
        # the landing point by finite differences.
        try:
            cov = np.linalg.inv(jac.T @ jac + 1e-9 * np.eye(6))
            dof = max(1, 2 * int(inliers.sum()) - 6)
            factor = max(1.0, (rms / SIGMA_IMAGE) ** 2 * 2 * int(inliers.sum()) / dof)
            eps = np.array([1e-3, 1e-3, 1e-3, 1e-2, 1e-2, 1e-2])
            moved = touchdown(x[None] + np.diag(eps), net_after_s=float(at[-1]))
            if all(m is not None for m in moved):
                d = np.array(
                    [
                        (np.array(m["point"][:2]) - down["point"][:2]) / e
                        for m, e in zip(moved, eps)
                    ]
                ).T
                spread = d @ cov @ d.T * factor
                sigma = float(math.sqrt(max(np.trace(spread), 0)))
        except np.linalg.LinAlgError:
            sigma = None
    speed = float(np.linalg.norm(x[3:]))
    result = {
        "start": [float(v) for v in x[:3]],
        "velocity": [float(v) for v in x[3:]],
        "initial_speed_m_s": speed,
        "initial_speed_kmh": speed * 3.6,
        "rms": rms,
        "points": len(at),
        "inliers": int(inliers.sum()),
        "observed_s": float(at[-1] - at[0]),
        "last_observed_s": float(at[-1]),
        "touchdown": down,
        "sigma_m": sigma,
    }
    if down is not None:
        vel = np.array(down["velocity"])
        horizontal = float(np.linalg.norm(vel[:2]))
        result["landing_speed_m_s"] = float(np.linalg.norm(vel))
        result["landing_angle_deg"] = float(
            math.degrees(math.atan2(-vel[2], horizontal))
        )
        result["extrapolated_s"] = float(down["time_s"] - at[-1])
    # The speed a tenth of a second after the contact: at 30 frames per
    # second the first frames after a smash barely fix the speed at the
    # racket, but they fix this one well.
    _, _, early = integrate(x[None], SETTLED_S)
    result["launch_bound"] = bool(initially_capped)
    timed_speed = (
        None
        if initially_capped or speed * 3.6 >= 440
        else early_track_speed(
            camera, x, at, observed, inliers, resolved_clock=resolved_clock
        )
    )
    result["launch_supported"] = timed_speed is not None
    result["early_speed_kmh"] = timed_speed
    result["settled_supported"] = bool(
        np.any(inliers & (at >= SETTLED_S - 0.06) & (at < SETTLED_S))
        and np.any(inliers & (at >= SETTLED_S) & (at <= SETTLED_S + 0.06))
    )
    result["speed_settled_kmh"] = float(np.linalg.norm(early[-1, 0]) * 3.6)
    end = positions_at(x[None], at[-1:])[0, 0]
    result["end_point"] = [float(v) for v in end]
    _grid_t, ps, _ = integrate(x[None], min(4.0, (down or {}).get("time_s", 2.0)))
    result["apex_m"] = float(ps[:, 0, 2].max())
    return result


__all__ = [
    "GRAVITY",
    "NET_HEIGHT",
    "NET_Y",
    "TERMINAL_VELOCITY",
    "Camera",
    "camera_from_homography",
    "fit_flight",
    "integrate",
    "positions_at",
    "touchdown",
]
