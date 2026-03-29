import React from "react";

export function ScenarioCard({
  name,
  variant,
  price,
  disc,
  assumptions,
}: {
  name: string;
  variant: "base" | "upside" | "downside";
  price: number;
  disc: number;
  assumptions: { segment: string; growth: number; margin: number }[];
}) {
  const discClass = disc >= 0 ? "positive" : "negative";
  return (
    <article className={`scenario-card scenario-card--${variant}`}>
      <h3>{name}</h3>
      <p className="price">${price?.toFixed(2)}</p>
      <p className={`disc ${discClass}`}>
        {disc >= 0 ? "+" : ""}
        {disc?.toFixed(1)}% vs spot
      </p>
      <ul>
        {assumptions.map((a) => (
          <li key={a.segment}>
            <strong>{a.segment}</strong>
            Growth {(a.growth * 100).toFixed(1)}% · margin {(a.margin * 100).toFixed(1)}%
          </li>
        ))}
      </ul>
    </article>
  );
}
