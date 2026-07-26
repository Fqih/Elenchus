import type { Claim, VerdictLabel } from "../types";
import "./App.css";

export function ClaimSpan({
  claim,
  label,
  onClick,
}: {
  claim: Claim;
  label: VerdictLabel;
  onClick: () => void;
}) {
  return (
    <span
      className={`claim claim-${label}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onClick();
      }}
    >
      {claim.text}
    </span>
  );
}