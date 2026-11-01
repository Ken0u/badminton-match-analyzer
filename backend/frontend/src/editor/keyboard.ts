const interactive = [
  "button",
  "input",
  "textarea",
  "select",
  "a[href]",
  "summary",
  '[contenteditable]:not([contenteditable="false"])',
  ...[
    "button",
    "link",
    "checkbox",
    "radio",
    "switch",
    "slider",
    "spinbutton",
    "textbox",
    "combobox",
    "listbox",
    "option",
    "menuitem",
    "tab",
    "treeitem",
  ].map((role) => `[role="${role}"]`),
].join(",");

export function isTransportShortcutControl(
  tagName: string,
  id: string,
  inTransport: boolean,
): boolean {
  return (
    tagName === "BUTTON" &&
    inTransport &&
    ["back-frame", "play", "next-frame"].includes(id)
  );
}

export function ownsEditorShortcuts(target: Element | null): boolean {
  const control = target?.closest(interactive);
  if (!control) return true;
  // Space on these existing transport buttons deliberately toggles playback.
  // All other controls, including nested targets, keep native keyboard behavior.
  return isTransportShortcutControl(
    control.tagName,
    control.id,
    control.closest(".transport") !== null,
  );
}
