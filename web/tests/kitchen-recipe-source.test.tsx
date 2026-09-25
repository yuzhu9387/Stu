import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { RecipeSource } from "@/features/kitchen/recipes";
it("renders uploaded recipe sources as image previews without exposing base64 text",()=>{
  const source="data:image/png;base64,iVBORw0KGgo=";
  render(<RecipeSource source={source}/>);
  expect(screen.getByRole("img",{name:"Original uploaded recipe"})).toHaveAttribute("src",source);
  expect(screen.queryByText(source)).not.toBeInTheDocument();
});
