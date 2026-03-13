import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DraftBoard } from "./DraftBoard";
import type { DraftState } from "../types";

const champions = [
  {
    champion_id: 103,
    key: "Ahri",
    name: "Ahri",
    image_url: "https://example.com/ahri.png",
    roles: ["middle"],
    patch: "16.5.1",
  },
  {
    champion_id: 412,
    key: "Thresh",
    name: "Thresh",
    image_url: "https://example.com/thresh.png",
    roles: ["support"],
    patch: "16.5.1",
  },
];

const draftState: DraftState = {
  phase: "BAN_PICK",
  timer_seconds_left: 28,
  local_player_cell_id: 3,
  local_player_assigned_role: "middle",
  local_player_effective_role: "middle",
  current_actor_cell_id: 6,
  current_action_type: "pick",
  my_team_picks: [
    {
      cell_id: 1,
      champion_id: 0,
      champion_name: null,
      champion_image_url: null,
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
      champion_name: null,
      champion_image_url: null,
      assigned_role: "jungle",
      effective_role: "jungle",
      role_source: "manual",
      role_confidence: 1,
      role_candidates: [{ role: "jungle", confidence: 1 }],
      is_local_player: false,
    },
    {
      cell_id: 3,
      champion_id: 0,
      champion_name: null,
      champion_image_url: null,
      assigned_role: "middle",
      effective_role: "middle",
      role_source: "manual",
      role_confidence: 1,
      role_candidates: [{ role: "middle", confidence: 1 }],
      is_local_player: true,
    },
    {
      cell_id: 4,
      champion_id: 0,
      champion_name: null,
      champion_image_url: null,
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
      champion_name: null,
      champion_image_url: null,
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
      champion_id: 103,
      champion_name: "Ahri",
      champion_image_url: "https://example.com/ahri.png",
      assigned_role: "middle",
      effective_role: "middle",
      role_source: "lcu",
      role_confidence: 1,
      role_candidates: [{ role: "middle", confidence: 1 }],
      is_local_player: false,
    },
  ],
  my_team_declared_roles: ["middle"],
  enemy_team_declared_roles: ["middle"],
  my_bans: [0, 0, 0, 0, 0],
  enemy_bans: [0, 0, 0, 0, 0],
  session_status: "active",
  patch: "16.5.1",
  queue_type: "RANKED_SOLO_5x5",
  is_local_players_turn: false,
};

describe("DraftBoard", () => {
  it("renders the current enemy pick and highlights the active actor", () => {
    render(
      <DraftBoard
        champions={champions}
        draftState={draftState}
        lcuConnected
        targetCellId={3}
        localPlayerCellId={3}
        onSlotChampionChange={vi.fn()}
        onSlotRoleChange={vi.fn()}
        onTargetSlotChange={vi.fn()}
        onRecommendForMe={vi.fn()}
        onBanChange={vi.fn()}
      />
    );

    expect(screen.getByRole("img", { name: "Ahri" })).toBeInTheDocument();
    expect(screen.getByText("Picking now")).toBeInTheDocument();
  });

  it("emits role changes for enemy slots", async () => {
    const user = userEvent.setup();
    const onSlotRoleChange = vi.fn();

    render(
      <DraftBoard
        champions={champions}
        draftState={draftState}
        lcuConnected={false}
        targetCellId={3}
        localPlayerCellId={3}
        onSlotChampionChange={vi.fn()}
        onSlotRoleChange={onSlotRoleChange}
        onTargetSlotChange={vi.fn()}
        onRecommendForMe={vi.fn()}
        onBanChange={vi.fn()}
      />
    );

    await user.selectOptions(screen.getByLabelText("Enemy 1 role"), "support");

    expect(onSlotRoleChange).toHaveBeenCalledWith("enemy", 6, "support");
  });

  it("shows unknown instead of defaulting empty enemy roles to top", () => {
    const unknownRoleDraftState: DraftState = {
      ...draftState,
      enemy_team_picks: [
        {
          ...draftState.enemy_team_picks[0],
          assigned_role: null,
          effective_role: null,
          role_source: "unknown",
          role_confidence: 0,
          role_candidates: [],
        },
      ],
    };

    render(
      <DraftBoard
        champions={champions}
        draftState={unknownRoleDraftState}
        lcuConnected
        targetCellId={3}
        localPlayerCellId={3}
        onSlotChampionChange={vi.fn()}
        onSlotRoleChange={vi.fn()}
        onTargetSlotChange={vi.fn()}
        onRecommendForMe={vi.fn()}
        onBanChange={vi.fn()}
      />
    );

    const roleSelect = screen.getByLabelText("Enemy 1 role");
    expect(roleSelect).toHaveValue("__unknown__");
    expect(within(roleSelect).getByRole("option", { name: "Unknown" })).toBeInTheDocument();
  });

  it("opens the champion picker and emits selection changes", async () => {
    const user = userEvent.setup();
    const onSlotChampionChange = vi.fn();

    render(
      <DraftBoard
        champions={champions}
        draftState={draftState}
        lcuConnected={false}
        targetCellId={3}
        localPlayerCellId={3}
        onSlotChampionChange={onSlotChampionChange}
        onSlotRoleChange={vi.fn()}
        onTargetSlotChange={vi.fn()}
        onRecommendForMe={vi.fn()}
        onBanChange={vi.fn()}
      />
    );

    const enemyCard = screen.getByText("Enemy 1").closest("article");
    expect(enemyCard).not.toBeNull();
    await user.click(within(enemyCard as HTMLElement).getByRole("button"));
    await user.click(screen.getByRole("button", { name: /Thresh/i }));

    expect(onSlotChampionChange).toHaveBeenCalledWith("enemy", 6, 412);
  });

  it("lets the user retarget recommendations without changing the local role control", async () => {
    const user = userEvent.setup();
    const onTargetSlotChange = vi.fn();
    const onSlotRoleChange = vi.fn();

    render(
      <DraftBoard
        champions={champions}
        draftState={draftState}
        lcuConnected
        targetCellId={2}
        localPlayerCellId={3}
        onSlotChampionChange={vi.fn()}
        onSlotRoleChange={onSlotRoleChange}
        onTargetSlotChange={onTargetSlotChange}
        onRecommendForMe={vi.fn()}
        onBanChange={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: "Analyze Your slot" }));
    await user.selectOptions(screen.getByLabelText("Your slot role"), "support");

    expect(onTargetSlotChange).toHaveBeenCalledWith(3);
    expect(onSlotRoleChange).toHaveBeenCalledWith("ally", 3, "support");
    expect(screen.getByText("Target: Ally 2")).toBeInTheDocument();
  });
});
