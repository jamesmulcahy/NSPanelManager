import { useFormContext } from "react-hook-form";
import { JoinButton } from "../common/buttons";
import { Card } from "../common/layout";
import { typedFields } from "../common/typedFields";
import { FIRMWARE_DEFAULTS, validateFirmwareRelease, validateFirmwareRepo } from "./firmware";
import type { SettingsFormValues } from "./form";

const { TextInput } = typedFields<SettingsFormValues>();

/** The GitHub repository and release that Upload > Firmware from GitHub stages panel firmware from. */
export function FirmwareCard() {
  const { setValue } = useFormContext<SettingsFormValues>();
  const reset = (name: keyof typeof FIRMWARE_DEFAULTS) => setValue(name, FIRMWARE_DEFAULTS[name], { shouldDirty: true, shouldValidate: true });
  return (
    <Card title="Firmware source">
      <TextInput
        name="firmware_github_repo"
        label="GitHub repository"
        hint={`As owner/repository. Firmware is staged from its releases. Default: ${FIRMWARE_DEFAULTS.firmware_github_repo}`}
        validate={validateFirmwareRepo}
        button={<JoinButton onClick={() => reset("firmware_github_repo")}>Reset repository</JoinButton>}
      />
      <TextInput
        name="firmware_github_release"
        label="Release"
        hint={`"latest", or a release tag to pin. Default: ${FIRMWARE_DEFAULTS.firmware_github_release}`}
        validate={validateFirmwareRelease}
        button={<JoinButton onClick={() => reset("firmware_github_release")}>Reset release</JoinButton>}
      />
    </Card>
  );
}
