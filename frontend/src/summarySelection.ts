import type { SummaryArtifact, SummaryTarget } from "./types";


export function summaryTargetKey(target: SummaryTarget): string {
  return `${target.level}:${target.start ?? "whole"}`;
}

export function isSummaryTargetChecked(
  artifact: SummaryArtifact,
  selectedTargets: SummaryTarget[],
): boolean {
  return artifact.exists || selectedTargets.some(
    (target) => summaryTargetKey(target) === summaryTargetKey(artifact),
  );
}

export function toggleSummaryTarget(
  summaries: SummaryArtifact[],
  selectedTargets: SummaryTarget[],
  artifact: SummaryArtifact,
): SummaryTarget[] {
  if (artifact.exists) return selectedTargets;

  const selectedKeys = new Set(selectedTargets.map(summaryTargetKey));
  const artifactKey = summaryTargetKey(artifact);
  const shouldSelect = !selectedKeys.has(artifactKey);
  const bigs = summaries.filter((item) => item.level === "big");
  const mids = summaries.filter((item) => item.level === "mid");
  const whole = summaries.find((item) => item.level === "whole");

  const add = (item: SummaryArtifact) => {
    if (!item.exists) selectedKeys.add(summaryTargetKey(item));
  };
  const remove = (item: SummaryArtifact) => {
    if (!item.exists) selectedKeys.delete(summaryTargetKey(item));
  };
  const isChecked = (item: SummaryArtifact) => (
    item.exists || selectedKeys.has(summaryTargetKey(item))
  );
  const midsInBig = (big: SummaryArtifact) => mids.filter((mid) => (
    mid.start !== null
    && big.start !== null
    && mid.start >= big.start
    && mid.start <= big.end
  ));
  const parent = artifact.level === "mid"
    ? bigs.find((big) => midsInBig(big).some(
        (mid) => summaryTargetKey(mid) === artifactKey,
      ))
    : undefined;

  if (artifact.level === "whole") {
    if (shouldSelect) {
      summaries.forEach(add);
    } else {
      summaries.forEach(remove);
    }
  } else if (artifact.level === "big") {
    const children = midsInBig(artifact);
    if (shouldSelect) {
      add(artifact);
      children.forEach(add);
    } else {
      remove(artifact);
      children.forEach(remove);
      if (whole) remove(whole);
    }
  } else if (shouldSelect) {
    add(artifact);
    if (parent && midsInBig(parent).every(isChecked)) add(parent);
  } else {
    remove(artifact);
    if (parent) remove(parent);
    if (whole) remove(whole);
  }

  if (whole && bigs.length > 0 && bigs.every(isChecked)) {
    add(whole);
  }

  return summaries
    .filter((item) => !item.exists && selectedKeys.has(summaryTargetKey(item)))
    .map((item) => ({ level: item.level, start: item.start }));
}
