import { beforeEach, describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import NSPanelBox from "./NSPanelBox";
import { useEntityStatesStore, type INSPanelStatusData } from "../../stores/EntityStore";

const MAC = "aa:bb:cc:dd:ee:ff";

const panel = (overrides: Partial<INSPanelStatusData> = {}): INSPanelStatusData => ({
  id: 1,
  mac: MAC,
  name: "Hall",
  ip_address: "10.0.0.2",
  rssi: -50,
  temperature: 21.5,
  temperature_unit: "°C",
  ram_usage: 40,
  update_progress: 0,
  warnings: [],
  accepted: true,
  denied: false,
  default_room_id: 1,
  model: "sonoff",
  features: [],
  state: "online",
  ...overrides,
});

const show = (status: INSPanelStatusData) => {
  useEntityStatesStore.setState({ status: "loaded", nspanels: { [MAC]: status } });
  return render(<NSPanelBox mac={MAC} />);
};

describe("NSPanelBox", () => {
  beforeEach(() => {
    useEntityStatesStore.setState({ status: "none", nspanels: {} });
  });

  it("shows the temperature, reboot and both updates for a Sonoff panel", () => {
    const { container } = show(panel());

    expect(container.textContent).toContain("21.5°C");
    expect(container.textContent).not.toContain("hPa");
    expect(container.textContent).toContain("Reboot");
    expect(container.textContent).toContain("Update firmware");
    expect(container.textContent).toContain("Update GUI");
  });

  it("shows humidity and pressure when the status has them", () => {
    const { container } = show(panel({ model: "custom", has_humidity: true, has_pressure: true, humidity: 40.2, pressure: 101300 }));

    expect(container.textContent).toContain("40.2%");
    expect(container.textContent).toContain("1013.0 hPa");
  });

  it("shows no humidity or pressure for a panel that does not report them, whatever its model", () => {
    const { container } = show(panel({ model: "custom" }));

    expect(container.textContent).not.toContain("hPa");
    expect(container.querySelector('[id^="humidity-"]')).toBeNull();
  });

  it("hides the temperature row and Update GUI for a Waveshare P4 panel, but keeps reboot and firmware update", () => {
    const { container } = show(panel({ model: "waveshare_p4", features: ["lvgl_look", "no_tft", "no_temperature", "no_buttons", "no_relays"] }));

    expect(container.querySelector('[id^="temperature-"]')).toBeNull();
    expect(container.textContent).not.toContain("Update GUI");
    expect(container.textContent).toContain("Reboot");
    expect(container.textContent).toContain("Update firmware");
  });

  it("offers no actions for a model it does not know", () => {
    const { container } = show(panel({ model: "unknown" }));

    expect(container.textContent).not.toContain("Reboot");
    expect(container.textContent).not.toContain("Update firmware");
  });

  describe("build identity", () => {
    const build = (overrides = {}) => ({
      version: "build-1a2b3c4d",
      project: "firmware_espidf",
      build_date: "Nov 28 2026 07:08:09",
      idf_version: "v5.5.0",
      elf_sha256: "e".repeat(64),
      image_sha256: "9f8e7d6c" + "0".repeat(56),
      chip: "esp32",
      ota_partition: "ota_0",
      ...overrides,
    });

    it("shows the version and a short image sha", () => {
      const { getByTestId } = show(panel({ build: build() }));

      expect(getByTestId("panel-build").textContent).toBe("build-1a2b3c4d · 9f8e7d6c");
    });

    it("shows nothing for a panel that reports no build", () => {
      expect(show(panel()).queryByTestId("panel-build")).toBeNull();
      useEntityStatesStore.setState({ status: "none", nspanels: {} });
      expect(show(panel({ build: null })).queryByTestId("panel-build")).toBeNull();
    });

    it("names the staged version when the staged image is another one", () => {
      const { getByTestId } = show(panel({ build: build(), staged_build: build({ version: "build-5e6f7a8b", image_sha256: "1".repeat(64) }) }));

      expect(getByTestId("panel-build").textContent).toBe("build-1a2b3c4d · 9f8e7d6c → build-5e6f7a8b");
    });

    it("shows no staged version when the images are the same or the staged sha is unknown", () => {
      const same = show(panel({ build: build(), staged_build: build() }));
      expect(same.getByTestId("panel-build").textContent).toBe("build-1a2b3c4d · 9f8e7d6c");
      useEntityStatesStore.setState({ status: "none", nspanels: {} });
      same.unmount();

      const unknown = show(panel({ build: build(), staged_build: build({ version: "build-5e6f7a8b", image_sha256: "" }) }));
      expect(unknown.getByTestId("panel-build").textContent).toBe("build-1a2b3c4d · 9f8e7d6c");
    });
  });
});
