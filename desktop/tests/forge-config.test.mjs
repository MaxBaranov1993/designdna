import assert from "node:assert/strict";
import test from "node:test";
import config from "../forge.config.mjs";

test("Forge builds Windows, macOS and Linux artifacts with packaged runtime resources", () => {
  assert.equal(config.packagerConfig.asar.unpack, "workers/**");
  assert.ok(config.packagerConfig.ignore.some((pattern) => pattern.test("/runtime/python/designdna-python.exe")));
  assert.ok(config.packagerConfig.ignore.some((pattern) => pattern.test("/runtime/playwright/chromium/chrome.exe")));
  assert.ok(config.packagerConfig.ignore.some((pattern) => pattern.test("/.runtime-build/designdna-python.spec")));
  assert.ok(config.packagerConfig.ignore.some((pattern) => pattern.test("/out/DesignDNA-win32-x64/designdna.exe")));
  assert.ok(config.packagerConfig.ignore.every((pattern) => !pattern.test("/services/provider-chat.mjs")));
  assert.ok(config.packagerConfig.extraResource.some((value) => value.endsWith("app")));
  assert.ok(config.packagerConfig.extraResource.some((value) => value.endsWith("schema")));
  assert.ok(config.packagerConfig.extraResource.some((value) => value.endsWith("spike")));
  assert.ok(config.packagerConfig.extraResource.some((value) => value.endsWith("tools")));
  assert.ok(config.packagerConfig.extraResource.some((value) => value.endsWith("runtime")));
  assert.ok(config.makers.some((maker) => maker.name === "@electron-forge/maker-squirrel" && maker.platforms.includes("win32")));
  assert.ok(config.makers.some((maker) => maker.name === "@electron-forge/maker-dmg" && maker.platforms.includes("darwin")));
  assert.ok(config.makers.some((maker) => maker.name === "@electron-forge/maker-zip" && maker.platforms.includes("linux")));
  assert.ok(config.makers.some((maker) => maker.name === "@electron-forge/maker-deb" && maker.platforms.includes("linux")));
  assert.ok(config.makers.some((maker) => maker.name === "@electron-forge/maker-rpm" && maker.platforms.includes("linux")));
});
