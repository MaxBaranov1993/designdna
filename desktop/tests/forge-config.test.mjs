import assert from "node:assert/strict";
import test from "node:test";
import config from "../forge.config.mjs";

test("Forge builds Windows and macOS artifacts with packaged runtime resources", () => {
  assert.equal(config.packagerConfig.asar.unpack, "workers/**");
  assert.ok(config.packagerConfig.extraResource.some((value) => value.endsWith("app")));
  assert.ok(config.packagerConfig.extraResource.some((value) => value.endsWith("tools")));
  assert.ok(config.makers.some((maker) => maker.name === "@electron-forge/maker-squirrel" && maker.platforms.includes("win32")));
  assert.ok(config.makers.some((maker) => maker.name === "@electron-forge/maker-dmg" && maker.platforms.includes("darwin")));
});
