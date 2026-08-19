type EditorController = typeof import("./controller");

let loadedController: EditorController | null = null;
let controllerLoad: Promise<EditorController> | null = null;

/** Keep the geometry/editor engine out of the initial graph bundle. */
export function loadEditorController(): Promise<EditorController> {
  controllerLoad ??= import("./controller").then((controller) => {
    loadedController = controller;
    // Preserve the legacy window engine hooks once the editor is requested.
    void import("../engine");
    return controller;
  });
  return controllerLoad;
}

export function getLoadedEditorController(): EditorController | null {
  return loadedController;
}
