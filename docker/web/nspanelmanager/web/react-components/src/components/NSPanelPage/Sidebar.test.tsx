import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import Sidebar from "./Sidebar";
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
  render(<Sidebar nspanel_mac={MAC} />);
};

describe("Sidebar", () => {
  beforeEach(() => {
    useEntityStatesStore.setState({ status: "none", nspanels: {} });
  });

  it("offers every action and the temperature on a Sonoff panel", () => {
    show(panel());

    expect(screen.getByText("Reboot")).toBeInTheDocument();
    expect(screen.getByText("Update firmware")).toBeInTheDocument();
    expect(screen.getByText("Update GUI")).toBeInTheDocument();
    expect(screen.getByText(/Temp: 21.5/)).toBeInTheDocument();
    expect(screen.queryByText(/Humidity/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Pressure/)).not.toBeInTheDocument();
  });

  it("shows humidity and pressure from the panel's has_* flags, not its model", () => {
    show(panel({ model: "sonoff", has_humidity: true, has_pressure: true, humidity: 40.2, pressure: 101300 }));

    expect(screen.getByText(/Humidity: 40.2%/)).toBeInTheDocument();
    expect(screen.getByText(/Pressure: 1013.0 hPa/)).toBeInTheDocument();
  });

  it("does not show humidity for a legacy custom panel that reports none", () => {
    show(panel({ model: "custom" }));

    expect(screen.queryByText(/Humidity/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Pressure/)).not.toBeInTheDocument();
  });

  it("hides the temperature and Update GUI for a Waveshare P4 panel, which keeps reboot and firmware update", () => {
    show(panel({ model: "waveshare_p4", features: ["lvgl_look", "no_tft", "no_temperature", "no_buttons", "no_relays"] }));

    expect(screen.queryByText(/Temp/)).not.toBeInTheDocument();
    expect(screen.queryByText("Update GUI")).not.toBeInTheDocument();
    expect(screen.getByText("Reboot")).toBeInTheDocument();
    expect(screen.getByText("Update firmware")).toBeInTheDocument();
    expect(screen.getByText("Force update firmware")).toBeInTheDocument();
  });

  it("offers no actions for a model it does not know", () => {
    show(panel({ model: "unknown" }));

    expect(screen.queryByText("Reboot")).not.toBeInTheDocument();
    expect(screen.queryByText("Update firmware")).not.toBeInTheDocument();
  });
});
