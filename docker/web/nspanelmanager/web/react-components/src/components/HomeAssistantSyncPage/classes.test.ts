/// <reference types="node" />
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import areaField from "../RoomPage/HomeAssistantAreaField.tsx?raw";
import common from "./common.tsx?raw";
import entitiesStep from "./EntitiesStep.tsx?raw";
import syncPage from "./HomeAssistantSyncPage.tsx?raw";
import roomsStep from "./RoomsStep.tsx?raw";

// The manager serves a prebuilt Tailwind/daisyUI stylesheet (web/static/css/main.css) that is not
// regenerated from these sources, so a class it doesn't contain silently does nothing.
const css = readFileSync(resolve(__dirname, "../../../../static/css/main.css"), "utf8");
const sources: [string, string][] = [
  ["HomeAssistantSyncPage.tsx", syncPage],
  ["RoomsStep.tsx", roomsStep],
  ["EntitiesStep.tsx", entitiesStep],
  ["common.tsx", common],
  ["HomeAssistantAreaField.tsx", areaField],
];

function classNames(source: string): string[] {
  const names = new Set<string>();
  const add = (text: string) => {
    for (const token of text.split(/\s+/)) if (/^[a-z][\w\-/:.]*$/.test(token)) names.add(token);
  };
  for (const match of source.matchAll(/className="([^"]*)"/g)) add(match[1]);
  for (const match of source.matchAll(/className=\{`([^`]*)`\}/g)) {
    add(match[1].replace(/\$\{[^}]*\}/g, " "));
    // Classes picked inside ${...}, such as ${active ? "tab-active" : ""}.
    for (const expression of match[1].matchAll(/\$\{[^}]*\}/g)) for (const literal of expression[0].matchAll(/[?:]\s*"([^"]+)"/g)) add(literal[1]);
  }
  return [...names];
}

const selector = (name: string) => "." + name.replace(/[/:.[\]]/g, (char) => "\\" + char);
const defined = (name: string) => new RegExp(selector(name).replace(/[\\.]/g, (char) => "\\" + char) + "(?![\\w-])").test(css);

describe("sync page classes", () => {
  it.each(sources)("%s only uses classes that main.css defines", (_file, source) => {
    const missing = classNames(source).filter((name) => !defined(name));
    expect(missing).toEqual([]);
  });
});
