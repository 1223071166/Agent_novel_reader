import { describe, expect, it } from "vitest";

import {
  isSummaryTargetChecked,
  summaryTargetKey,
  toggleSummaryTarget,
} from "../summarySelection";
import type { SummaryArtifact, SummaryTarget } from "../types";


const summaries: SummaryArtifact[] = [
  { level: "mid", start: 1, end: 20, exists: false },
  { level: "mid", start: 21, end: 40, exists: false },
  { level: "big", start: 1, end: 40, exists: false },
  { level: "whole", start: null, end: 40, exists: false },
];

function keys(targets: SummaryTarget[]): string[] {
  return targets.map(summaryTargetKey);
}

describe("summary selection hierarchy", () => {
  it("selects and clears every descendant with the whole-book summary", () => {
    const selected = toggleSummaryTarget(summaries, [], summaries[3]);

    expect(keys(selected)).toEqual([
      "mid:1",
      "mid:21",
      "big:1",
      "whole:whole",
    ]);
    expect(toggleSummaryTarget(summaries, selected, summaries[3])).toEqual([]);
  });

  it("selects a big summary together with its mid summaries", () => {
    const selected = toggleSummaryTarget(summaries, [], summaries[2]);

    expect(keys(selected)).toEqual(["mid:1", "mid:21", "big:1", "whole:whole"]);
  });

  it("selects parents after every child is selected and clears them when one child is cleared", () => {
    const firstSelected = toggleSummaryTarget(summaries, [], summaries[0]);
    expect(keys(firstSelected)).toEqual(["mid:1"]);

    const allSelected = toggleSummaryTarget(summaries, firstSelected, summaries[1]);
    expect(keys(allSelected)).toEqual([
      "mid:1",
      "mid:21",
      "big:1",
      "whole:whole",
    ]);

    const oneCleared = toggleSummaryTarget(summaries, allSelected, summaries[0]);
    expect(keys(oneCleared)).toEqual(["mid:21"]);
  });

  it("keeps generated summaries checked and out of the mutable selection", () => {
    const generatedMid = { ...summaries[0], exists: true };
    const inventory = [generatedMid, ...summaries.slice(1)];

    expect(isSummaryTargetChecked(generatedMid, [])).toBe(true);
    expect(toggleSummaryTarget(inventory, [], generatedMid)).toEqual([]);

    const selected = toggleSummaryTarget(inventory, [], inventory[1]);
    expect(keys(selected)).toEqual(["mid:21", "big:1", "whole:whole"]);
  });

  it("does not select an unrelated parent whose children were generated earlier", () => {
    const inventory: SummaryArtifact[] = [
      { level: "mid", start: 1, end: 20, exists: true },
      { level: "big", start: 1, end: 20, exists: false },
      { level: "mid", start: 21, end: 40, exists: false },
      { level: "big", start: 21, end: 40, exists: false },
      { level: "whole", start: null, end: 40, exists: false },
    ];

    const selected = toggleSummaryTarget(inventory, [], inventory[2]);

    expect(keys(selected)).toEqual(["mid:21", "big:21"]);
  });
});
