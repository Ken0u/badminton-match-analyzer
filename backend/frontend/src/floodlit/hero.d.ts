// Types for the hero module, which stays JavaScript as ported from the
// approved prototype (see hero.js).
import type { Matrix, Speed } from "./model.js";

/** The parts of a match the hero reads: one or more rallies with tracks. */
export interface HeroMatch {
  analysis: {
    video: {
      fps: number;
      frame_count: number;
      width: number;
      height: number;
    };
    players: { id: string; name?: string | undefined; team: "T1" | "T2" }[];
    rallies: HeroRally[];
    tracks: {
      rate_hz: number;
      persons: {
        person_id: string;
        x: (number | null)[];
        y: (number | null)[];
      }[];
      shuttle?: { x: (number | null)[]; y: (number | null)[] };
    };
  };
  trackIndex: Map<string, HeroMatch["analysis"]["tracks"]["persons"][number]>;
  views: { start_frame: number; end_frame: number; inverse: Matrix }[];
}
export interface HeroRally {
  id: string;
  start_s: number;
  end_s: number;
  outcome?: { winner_team?: "T1" | "T2" | null; detail?: string | null } | null;
  shots: {
    id: string;
    frame: number;
    time_s: number;
    hitter_id?: string | null;
    [key: string]: unknown;
  }[];
}
export interface HeroShotEvent {
  index: number;
  total: number;
  shot: HeroRally["shots"][number];
  label: string;
  speed: Speed | null;
  rally: HeroRally;
}
export interface Hero {
  rally: HeroRally;
  won: {
    before: { T1: number; T2: number };
    after: { T1: number; T2: number };
  };
  destroy(): void;
}
export function pickRally(match: HeroMatch): HeroRally;
export function createHero(
  container: HTMLElement,
  match: HeroMatch,
  options?: {
    still?: boolean;
    phone?: boolean;
    onShot?: (event: HeroShotEvent) => void;
  },
): Hero;
