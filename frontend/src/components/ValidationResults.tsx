import React from "react";

export function ValidationResults({ val }: { val: { passed: boolean; issues?: unknown[] } }) {
  if (!val) return null;
  return (
    <div className={`validation ${val.passed ? "ok" : "warn"}`}>
      <h4>Validation {val.passed ? "passed" : "issues"}</h4>
      <pre>{JSON.stringify(val, null, 2)}</pre>
    </div>
  );
}
