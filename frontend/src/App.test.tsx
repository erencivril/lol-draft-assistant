import { buildRecommendPayload, resolveEnemyRoleSelection } from "./App";
import type { DraftState } from "./types";

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(),
}));

describe("buildRecommendPayload", () => {
  it("keeps the local slot in the payload while targeting another ally slot", () => {
    const draftState: DraftState = {
      phase: "BAN_PICK",
      local_player_cell_id: 3,
      local_player_assigned_role: "middle",
      local_player_effective_role: "middle",
      current_actor_cell_id: 3,
      current_action_type: "pick",
      my_team_picks: [
        {
          cell_id: 1,
          champion_id: 0,
          assigned_role: "top",
          effective_role: "top",
          role_source: "manual",
          role_confidence: 1,
          role_candidates: [{ role: "top", confidence: 1 }],
          is_local_player: false,
        },
        {
          cell_id: 2,
          champion_id: 0,
          assigned_role: "jungle",
          effective_role: "jungle",
          role_source: "manual",
          role_confidence: 1,
          role_candidates: [{ role: "jungle", confidence: 1 }],
          is_local_player: false,
        },
        {
          cell_id: 3,
          champion_id: 7,
          champion_name: "LeBlanc",
          assigned_role: "middle",
          effective_role: "middle",
          role_source: "lcu",
          role_confidence: 1,
          role_candidates: [{ role: "middle", confidence: 1 }],
          is_local_player: true,
        },
        {
          cell_id: 4,
          champion_id: 0,
          assigned_role: "bottom",
          effective_role: "bottom",
          role_source: "manual",
          role_confidence: 1,
          role_candidates: [{ role: "bottom", confidence: 1 }],
          is_local_player: false,
        },
        {
          cell_id: 5,
          champion_id: 0,
          assigned_role: "support",
          effective_role: "support",
          role_source: "manual",
          role_confidence: 1,
          role_candidates: [{ role: "support", confidence: 1 }],
          is_local_player: false,
        },
      ],
      enemy_team_picks: [
        {
          cell_id: 6,
          champion_id: 238,
          champion_name: "Zed",
          assigned_role: "middle",
          effective_role: "middle",
          role_source: "lcu",
          role_confidence: 1,
          role_candidates: [{ role: "middle", confidence: 1 }],
          is_local_player: false,
        },
      ],
      my_team_declared_roles: ["top", "jungle", "middle", "bottom", "support"],
      enemy_team_declared_roles: ["middle"],
      my_bans: [0, 0, 0, 0, 0],
      enemy_bans: [0, 0, 0, 0, 0],
      session_status: "active",
      patch: "16.5.1",
      queue_type: "RANKED_SOLO_5x5",
      is_local_players_turn: true,
    };

    const payload = buildRecommendPayload({ region: "TR", rank_tier: "emerald" }, draftState, 4);

    expect(payload.target_cell_id).toBe(4);
    expect(payload.ally_slots).toHaveLength(5);
    expect(payload.enemy_slots).toHaveLength(1);
    expect(payload.ally_slots).toContainEqual(
      expect.objectContaining({
        cell_id: 3,
        champion_id: 7,
        role: "middle",
        is_local_player: true,
      })
    );
  });

  it("releases the current enemy role owner when a newer manual role steals the lane", () => {
    const draftState: DraftState = {
      phase: "BAN_PICK",
      local_player_cell_id: 3,
      local_player_assigned_role: "middle",
      local_player_effective_role: "middle",
      current_actor_cell_id: 7,
      current_action_type: "pick",
      my_team_picks: [
        {
          cell_id: 1,
          champion_id: 0,
          assigned_role: "top",
          effective_role: "top",
          role_source: "manual",
          role_confidence: 1,
          role_candidates: [{ role: "top", confidence: 1 }],
          is_local_player: false,
        },
        {
          cell_id: 2,
          champion_id: 0,
          assigned_role: "jungle",
          effective_role: "jungle",
          role_source: "manual",
          role_confidence: 1,
          role_candidates: [{ role: "jungle", confidence: 1 }],
          is_local_player: false,
        },
        {
          cell_id: 3,
          champion_id: 7,
          assigned_role: "middle",
          effective_role: "middle",
          role_source: "lcu",
          role_confidence: 1,
          role_candidates: [{ role: "middle", confidence: 1 }],
          is_local_player: true,
        },
        {
          cell_id: 4,
          champion_id: 0,
          assigned_role: "bottom",
          effective_role: "bottom",
          role_source: "manual",
          role_confidence: 1,
          role_candidates: [{ role: "bottom", confidence: 1 }],
          is_local_player: false,
        },
        {
          cell_id: 5,
          champion_id: 0,
          assigned_role: "support",
          effective_role: "support",
          role_source: "manual",
          role_confidence: 1,
          role_candidates: [{ role: "support", confidence: 1 }],
          is_local_player: false,
        },
      ],
      enemy_team_picks: [
        {
          cell_id: 6,
          champion_id: 266,
          assigned_role: "top",
          effective_role: "top",
          role_source: "manual",
          role_confidence: 1,
          role_candidates: [{ role: "top", confidence: 1 }],
          is_local_player: false,
        },
        {
          cell_id: 7,
          champion_id: 19,
          assigned_role: "jungle",
          effective_role: "jungle",
          role_source: "inferred",
          role_confidence: 0.88,
          role_candidates: [{ role: "jungle", confidence: 0.88 }],
          is_local_player: false,
        },
      ],
      my_team_declared_roles: ["top", "jungle", "middle", "bottom", "support"],
      enemy_team_declared_roles: ["top", "jungle"],
      my_bans: [0, 0, 0, 0, 0],
      enemy_bans: [0, 0, 0, 0, 0],
      session_status: "active",
      patch: "16.5.1",
      queue_type: "RANKED_SOLO_5x5",
      is_local_players_turn: true,
    };

    const selection = resolveEnemyRoleSelection(draftState, 7, "top");

    expect(selection.releasedCellId).toBe(6);
    expect(selection.toastText).toContain("Enemy 2 took Top");
    expect(selection.toastText).toContain("Enemy 1 was re-inferred");
  });
});
