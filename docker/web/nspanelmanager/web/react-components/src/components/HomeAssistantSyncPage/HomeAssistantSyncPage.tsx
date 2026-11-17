import { useState } from "react";
import EntitiesStep from "./EntitiesStep";
import RoomsStep from "./RoomsStep";

type Step = "rooms" | "entities";

export default function HomeAssistantSyncPage() {
  const [step, setStep] = useState<Step>("rooms");

  return (
    <div>
      <div className="flex items-center justify-between">
        <h2 className="text-2xl">Sync from Home Assistant</h2>
        <a href="/rooms" className="btn btn-outline btn-info">
          Back to rooms
        </a>
      </div>
      <div role="tablist" className="tabs tabs-box tabs-lg my-4">
        <button type="button" role="tab" aria-selected={step === "rooms"} className={`tab font-semibold ${step === "rooms" ? "tab-active" : ""}`} onClick={() => setStep("rooms")}>
          1. Rooms
        </button>
        <button type="button" role="tab" aria-selected={step === "entities"} className={`tab font-semibold ${step === "entities" ? "tab-active" : ""}`} onClick={() => setStep("entities")}>
          2. Entities
        </button>
      </div>
      {step === "rooms" ? <RoomsStep /> : <EntitiesStep onShowRooms={() => setStep("rooms")} />}
    </div>
  );
}
