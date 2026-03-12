import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AnalysisFiltersPanel } from "./AnalysisFiltersPanel";

describe("AnalysisFiltersPanel", () => {
  it("emits updated filters when the user changes the rank", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <AnalysisFiltersPanel
        filters={{ region: "TR", rank_tier: "silver", role: "middle" }}
        onChange={onChange}
      />
    );

    await user.selectOptions(screen.getByLabelText("Analysis rank"), "emerald_plus");

    expect(onChange).toHaveBeenCalledWith({
      region: "TR",
      rank_tier: "emerald_plus",
      role: "middle",
    });
  });

  it("disables the controls when requested", () => {
    render(
      <AnalysisFiltersPanel
        filters={{ region: "TR", rank_tier: "silver", role: "middle" }}
        disabled
        onChange={vi.fn()}
      />
    );

    expect(screen.getByLabelText("Analysis region")).toBeDisabled();
    expect(screen.getByLabelText("Analysis rank")).toBeDisabled();
    expect(screen.getByLabelText("Analysis role")).toBeDisabled();
  });
});
