import { render, screen } from "@testing-library/react";
import { PhaseIndicator } from "./PhaseIndicator";
import type { DraftState } from "../types";

const baseDraftState: DraftState = {
  phase: "BAN_PICK",
  timer_seconds_left: 24,
  local_player_cell_id: 1,
  local_player_assigned_role: "jungle",
  local_player_effective_role: "jungle",
  current_actor_cell_id: 6,
  current_action_type: "pick",
  my_team_picks: [
    {
      cell_id: 1,
      champion_id: 64,
      champion_name: "Lee Sin",
      champion_image_url: null,
      assigned_role: "jungle",
      effective_role: "jungle",
      role_source: "lcu",
      role_confidence: 1,
      role_candidates: [{ role: "jungle", confidence: 1 }],
      is_local_player: true,
    },
  ],
  enemy_team_picks: [
    {
      cell_id: 6,
      champion_id: 103,
      champion_name: "Ahri",
      champion_image_url: null,
      assigned_role: null,
      effective_role: "middle",
      role_source: "inferred",
      role_confidence: 0.72,
      role_candidates: [{ role: "middle", confidence: 0.72 }],
      is_local_player: false,
    },
  ],
  my_team_declared_roles: ["jungle"],
  enemy_team_declared_roles: ["middle"],
  my_bans: [],
  enemy_bans: [],
  session_status: "active",
  patch: "16.5.1",
  queue_type: "CUSTOM",
  is_local_players_turn: false,
};

describe("PhaseIndicator", () => {
  it("shows which side is currently acting", () => {
    render(<PhaseIndicator draftState={baseDraftState} />);

    expect(screen.getByText("Enemy team is picking")).toBeInTheDocument();
    expect(screen.getByText("(middle)")).toBeInTheDocument();
  });

  it("shows your turn copy when the local player is acting", () => {
    render(
      <PhaseIndicator
        draftState={{
          ...baseDraftState,
          current_actor_cell_id: 1,
          is_local_players_turn: true,
        }}
      />
    );

    expect(screen.getByText("Your Turn to Pick")).toBeInTheDocument();
    expect(screen.getByText("(jungle)")).toBeInTheDocument();
  });
});
