import type { ChampionCatalogItem } from "../api/client";
import { inferDraftRoles } from "./draftRoleInference";
import type { DraftState, TeamSlot } from "../types";

function createSlot(
  cellId: number,
  championId: number,
  overrides: Partial<TeamSlot> = {}
): TeamSlot {
  return {
    cell_id: cellId,
    champion_id: championId,
    champion_name: null,
    champion_image_url: null,
    assigned_role: null,
    effective_role: null,
    role_source: "unknown",
    role_confidence: 0,
    role_candidates: [],
    is_local_player: false,
    ...overrides,
  };
}

const championLookup = new Map<number, ChampionCatalogItem>([
  [
    1,
    {
      champion_id: 1,
      key: "KSante",
      name: "K'Sante",
      image_url: "https://example.com/ksante.png",
      roles: ["top"],
      patch: "16.5.1",
    },
  ],
  [
    2,
    {
      champion_id: 2,
      key: "Wukong",
      name: "Wukong",
      image_url: "https://example.com/wukong.png",
      roles: ["top", "jungle"],
      patch: "16.5.1",
    },
  ],
  [
    3,
    {
      champion_id: 3,
      key: "Ahri",
      name: "Ahri",
      image_url: "https://example.com/ahri.png",
      roles: ["middle"],
      patch: "16.5.1",
    },
  ],
  [
    4,
    {
      champion_id: 4,
      key: "Jinx",
      name: "Jinx",
      image_url: "https://example.com/jinx.png",
      roles: ["bottom"],
      patch: "16.5.1",
    },
  ],
  [
    5,
    {
      champion_id: 5,
      key: "Leona",
      name: "Leona",
      image_url: "https://example.com/leona.png",
      roles: ["support"],
      patch: "16.5.1",
    },
  ],
]);

const baseDraftState: DraftState = {
  phase: "BAN_PICK",
  timer_seconds_left: 20,
  local_player_cell_id: 3,
  local_player_assigned_role: "middle",
  local_player_effective_role: "middle",
  current_actor_cell_id: 6,
  current_action_type: "pick",
  my_team_picks: [
    createSlot(1, 0, {
      assigned_role: "top",
      effective_role: "top",
      role_source: "manual",
      role_confidence: 1,
      role_candidates: [{ role: "top", confidence: 1 }],
    }),
    createSlot(2, 0, {
      assigned_role: "jungle",
      effective_role: "jungle",
      role_source: "manual",
      role_confidence: 1,
      role_candidates: [{ role: "jungle", confidence: 1 }],
    }),
    createSlot(3, 0, {
      assigned_role: "middle",
      effective_role: "middle",
      role_source: "manual",
      role_confidence: 1,
      role_candidates: [{ role: "middle", confidence: 1 }],
      is_local_player: true,
    }),
    createSlot(4, 0, {
      assigned_role: "bottom",
      effective_role: "bottom",
      role_source: "manual",
      role_confidence: 1,
      role_candidates: [{ role: "bottom", confidence: 1 }],
    }),
    createSlot(5, 0, {
      assigned_role: "support",
      effective_role: "support",
      role_source: "manual",
      role_confidence: 1,
      role_candidates: [{ role: "support", confidence: 1 }],
    }),
  ],
  enemy_team_picks: [
    createSlot(6, 1),
    createSlot(7, 2),
    createSlot(8, 3),
    createSlot(9, 4),
    createSlot(10, 5),
  ],
  my_team_declared_roles: ["top", "jungle", "middle", "bottom", "support"],
  enemy_team_declared_roles: [],
  my_bans: [0, 0, 0, 0, 0],
  enemy_bans: [0, 0, 0, 0, 0],
  session_status: "active",
  patch: "16.5.1",
  queue_type: "RANKED_SOLO_5x5",
  is_local_players_turn: false,
};

describe("inferDraftRoles", () => {
  it("infers unique enemy roles from champion lane pools", () => {
    const resolved = inferDraftRoles(baseDraftState, championLookup);

    expect(resolved.enemy_team_picks.map((slot) => slot.effective_role)).toEqual([
      "top",
      "jungle",
      "middle",
      "bottom",
      "support",
    ]);
    expect(resolved.enemy_team_picks.every((slot) => slot.role_source === "inferred")).toBe(true);
  });

  it("keeps explicit LCU roles instead of overriding them", () => {
    const draftState: DraftState = {
      ...baseDraftState,
      enemy_team_picks: [
        createSlot(6, 2, {
          assigned_role: "jungle",
          effective_role: "jungle",
          role_source: "lcu",
          role_confidence: 1,
          role_candidates: [{ role: "jungle", confidence: 1 }],
        }),
        ...baseDraftState.enemy_team_picks.slice(1),
      ],
    };

    const resolved = inferDraftRoles(draftState, championLookup);

    expect(resolved.enemy_team_picks[0].effective_role).toBe("jungle");
    expect(resolved.enemy_team_picks[0].role_source).toBe("lcu");
  });
});
