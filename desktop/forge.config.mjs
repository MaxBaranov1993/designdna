import path from "node:path";
import { fileURLToPath } from "node:url";

const desktopDirectory = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(desktopDirectory, "..");
const signedMac = Boolean(process.env.APPLE_ID && process.env.APPLE_APP_PASSWORD && process.env.APPLE_TEAM_ID);
const signedWindows = Boolean(process.env.WINDOWS_CERTIFICATE_FILE && process.env.WINDOWS_CERTIFICATE_PASSWORD);

export default {
  packagerConfig: {
    name: "DesignDNA",
    executableName: "designdna",
    appBundleId: "net.rsale.designdna",
    appCategoryType: "public.app-category.developer-tools",
    asar: { unpack: "workers/**" },
    extraResource: [
      path.join(projectRoot, "app"),
      path.join(projectRoot, "schema"),
      path.join(projectRoot, "spike"),
      path.join(projectRoot, "tools"),
      path.join(desktopDirectory, "runtime"),
    ],
    ...(signedMac ? {
      osxSign: {},
      osxNotarize: { tool: "notarytool", appleId: process.env.APPLE_ID, appleIdPassword: process.env.APPLE_APP_PASSWORD, teamId: process.env.APPLE_TEAM_ID },
    } : {}),
  },
  makers: [
    {
      name: "@electron-forge/maker-squirrel",
      platforms: ["win32"],
      config: {
        name: "designdna",
        authors: "DesignDNA",
        description: "Local-first AI web-design studio",
        ...(signedWindows ? { certificateFile: process.env.WINDOWS_CERTIFICATE_FILE, certificatePassword: process.env.WINDOWS_CERTIFICATE_PASSWORD } : {}),
      },
    },
    { name: "@electron-forge/maker-zip", platforms: ["darwin"] },
    { name: "@electron-forge/maker-dmg", platforms: ["darwin"], config: { format: "ULFO" } },
  ],
};
