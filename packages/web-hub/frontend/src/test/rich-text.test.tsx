import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { RichText } from "@/features/chats/rich-text";

it("renders a Markdown table with semantic headers and cells", () => {
  render(
    <RichText content={[
      "| Bereich | Status |",
      "| --- | --- |",
      "| API | Dokumentiert |",
      "| Datenbank | Read-only |",
    ].join("\n")} />,
  );

  expect(screen.getByRole("table")).toBeVisible();
  expect(screen.getByRole("columnheader", { name: "Bereich" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "Read-only" })).toBeVisible();
});

it("links only relative targets accepted by an explicit resolver", () => {
  render(
    <RichText
      content="[API](API_REFERENCE.md) und [Unsicher](javascript:alert(1))"
      resolveLink={(href) => href === "API_REFERENCE.md"
        ? "/docs/control-plane/api"
        : undefined}
    />,
  );

  expect(screen.getByRole("link", { name: "API" })).toHaveAttribute(
    "href",
    "/docs/control-plane/api",
  );
  expect(screen.queryByRole("link", { name: "Unsicher" })).not.toBeInTheDocument();
  expect(screen.getByText("Unsicher").tagName).toBe("CODE");
});
