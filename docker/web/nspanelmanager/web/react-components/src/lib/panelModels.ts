// The panel models the UI knows. A model selects the firmware slot and nothing else: what a board has or lacks is read
// from the features it registered with (INSPanelStatusData.features) and the has_* flags of its status, never from the
// model. Adding a board is one entry here (and in board_models.py and nspanel_model.hpp).
export const KNOWN_MODELS = ["sonoff", "custom", "waveshare_p4"] as const;

export type PanelModel = (typeof KNOWN_MODELS)[number];

export type PanelFeature = "no_tft" | "no_temperature" | "no_buttons" | "no_relays";

export const isKnownModel = (model: string | undefined): model is PanelModel => KNOWN_MODELS.includes(model as PanelModel);

export const hasFeature = (status: { features?: string[] }, feature: PanelFeature): boolean => (status.features ?? []).includes(feature);
