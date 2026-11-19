// Where the manager stages panel firmware from (Upload > Firmware from GitHub).
export const FIRMWARE_DEFAULTS = {
  firmware_github_repo: "jamesmulcahy/NSPanelManager-firmware",
  firmware_github_release: "latest",
} as const;

const REPO = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const TAG = /^[A-Za-z0-9_.-]{1,100}$/;

/** true when the repository is fine, or the error message. */
export function validateFirmwareRepo(value: string): true | string {
  return REPO.test(value) ? true : "Use the form owner/repository, with letters, digits, dots, dashes and underscores.";
}

/** true when the release is fine ("latest" or a tag), or the error message. */
export function validateFirmwareRelease(value: string): true | string {
  return TAG.test(value) ? true : 'Use "latest" or a release tag of up to 100 letters, digits, dots, dashes and underscores.';
}
