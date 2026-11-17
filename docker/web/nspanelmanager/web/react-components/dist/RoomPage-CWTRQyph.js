import { c as __toESM, r as require_react, t as require_jsx_runtime } from "./main-CQgkDirJ.js";
import { r as useAvailableEntitiesStore } from "./MultiStep_AddEditEntity-B71P2D0P.js";
import { t as useSettingsStore } from "./SettingsStore-CxLpnkPU.js";
import { t as StateManagedSelect$1 } from "./react-select.esm-tO78glWd.js";
import { l as useWatch, s as useForm } from "./index.esm-8YJeVMft.js";
import { n as Notify } from "./NSPanelToastContainer-ajQpaG1t.js";
import EntitiesPagesView from "./EntitiesPagesView-BUmrlsZU.js";
import { t as api } from "./client-CRfCe5X7.js";
import { p as errorMessage } from "./sync-Dde6AJAS.js";
import { t as useStompStore } from "./StompStore-Bu_NjXtP.js";
import { t as useEntityStatesStore } from "./EntityStore-Dw7rF-_D.js";
import { d as mdiTextShort, x as require_Icon } from "./mdi-CQAOves1.js";
//#region src/components/RoomPage/HomeAssistantAreaField.tsx
var import_Icon = require_Icon();
var import_react = /* @__PURE__ */ __toESM(require_react(), 1);
var import_jsx_runtime = require_jsx_runtime();
var UNSET = "__unset__";
var NONE = "__none__";
var toChoice = (room) => room.home_assistant_link === "linked" ? room.home_assistant_area_id ?? "" : room.home_assistant_link === "none" ? NONE : UNSET;
/**
* The "Home Assistant area" field of the room page. It saves on its own (PATCH /rest/v2/rooms/<id>),
* because the rest of the form goes through the older /rest/rooms endpoint.
*/
function HomeAssistantAreaField({ roomId }) {
	const [room, setRoom] = (0, import_react.useState)(null);
	const [areas, setAreas] = (0, import_react.useState)(null);
	const [areasError, setAreasError] = (0, import_react.useState)(null);
	const [loadError, setLoadError] = (0, import_react.useState)(null);
	const [choice, setChoice] = (0, import_react.useState)(UNSET);
	const { status: settingsStatus, settings, fetchData } = useSettingsStore();
	const tokenSet = settings?.home_assistant_token_set ?? false;
	const [saving, setSaving] = (0, import_react.useState)(false);
	const [message, setMessage] = (0, import_react.useState)(null);
	(0, import_react.useEffect)(() => {
		if (settingsStatus === "none") fetchData();
	}, [settingsStatus, fetchData]);
	(0, import_react.useEffect)(() => {
		let current = true;
		api.GET("/rest/v2/rooms/{id}", { params: { path: { id: roomId } } }).then(({ data, error, response }) => {
			if (!current) return;
			if (data) {
				setRoom(data);
				setChoice(toChoice(data));
			} else setLoadError(errorMessage(error, response));
		}).catch((caught) => current && setLoadError(errorMessage(caught)));
		return () => {
			current = false;
		};
	}, [roomId]);
	(0, import_react.useEffect)(() => {
		if (!tokenSet) return;
		let current = true;
		api.GET("/rest/v2/home_assistant/areas").then(({ data, error, response }) => {
			if (!current) return;
			if (data) setAreas(data);
			else setAreasError(errorMessage(error, response));
		}).catch((caught) => current && setAreasError(errorMessage(caught)));
		return () => {
			current = false;
		};
	}, [tokenSet]);
	if (loadError) return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		role: "alert",
		className: "alert alert-error my-2",
		children: ["Couldn't load the Home Assistant area: ", loadError]
	});
	if (!room || settingsStatus === "loaded" && !tokenSet && room.home_assistant_link === "unset") return null;
	const missing = room.home_assistant_link === "linked" && areas !== null && !areas.some((area) => area.area_id === room.home_assistant_area_id);
	const dirty = choice !== toChoice(room);
	async function save() {
		if (!room) return;
		setSaving(true);
		setMessage(null);
		const body = choice === UNSET ? { home_assistant_link: "unset" } : choice === NONE ? { home_assistant_link: "none" } : {
			home_assistant_link: "linked",
			home_assistant_area_id: choice
		};
		try {
			const { data, error, response } = await api.PATCH("/rest/v2/rooms/{id}", {
				params: { path: { id: roomId } },
				body
			});
			if (data) {
				setRoom(data);
				setChoice(toChoice(data));
				setMessage({
					kind: "success",
					text: "Saved the Home Assistant area."
				});
			} else setMessage({
				kind: "error",
				text: `Couldn't save the Home Assistant area: ${errorMessage(error, response)}`
			});
		} catch (caught) {
			setMessage({
				kind: "error",
				text: errorMessage(caught)
			});
		} finally {
			setSaving(false);
		}
	}
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		className: "my-2 w-full md:ms-1",
		children: [
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)("label", {
				htmlFor: "home_assistant_area",
				className: "block mb-2 text-sm font-medium",
				children: "Home Assistant area"
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "flex items-center gap-2",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("select", {
					id: "home_assistant_area",
					className: "select bg-base-300 flex-1",
					value: choice,
					onChange: (event) => setChoice(event.target.value),
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
							value: UNSET,
							children: "Not set"
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
							value: NONE,
							children: "None"
						}),
						missing && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("option", {
							value: room.home_assistant_area_id ?? "",
							children: [room.home_assistant_area_id, " (missing)"]
						}),
						(areas ?? []).map((area) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
							value: area.area_id,
							disabled: area.linked_room_id !== null && area.linked_room_id !== roomId,
							children: area.name
						}, area.area_id))
					]
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
					type: "button",
					className: "btn btn-info",
					disabled: !dirty || saving,
					onClick: save,
					children: "Save area"
				})]
			}),
			missing && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: "text-sm text-warning mt-1",
				children: "Area missing in Home Assistant. The room stays linked; pick another area, or choose None."
			}),
			areasError && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
				className: "text-sm text-error mt-1",
				children: ["Couldn't load the Home Assistant areas: ", areasError]
			}),
			message && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				role: "status",
				className: `text-sm mt-1 ${message.kind === "error" ? "text-error" : "text-success"}`,
				children: message.text
			})
		]
	});
}
//#endregion
//#region src/components/RoomPage/RoomPage.tsx
function RoomPage({ room_id }) {
	const { status: stompStatus } = useStompStore();
	const { status: entityStatus, rooms, _nspanels } = useEntityStatesStore();
	const home_assistant_options = useAvailableEntitiesStore((s) => s.home_assistant_options);
	const openhab_options = useAvailableEntitiesStore((s) => s.openhab_options);
	const all_options = [...home_assistant_options.filter((option) => option.value.startsWith("sensor.")), ...openhab_options];
	const room = rooms[room_id];
	const [hasLoadedValues, setHasLoadedValues] = (0, import_react.useState)(false);
	const delete_confirm_dialog_ref = (0, import_react.useRef)(null);
	const can_delete = Object.keys(rooms).length > 1 || _nspanels.length === 0;
	const { control, register, getValues, setValue, reset, handleSubmit } = useForm({ defaultValues: {
		id: room?.id,
		friendly_name: room?.friendly_name,
		room_temp_provider: room?.room_temp_provider,
		room_temp_sensor: room?.room_temp_sensor
	} });
	useWatch({
		control,
		name: "room_temp_sensor"
	});
	const current_friendly_name = useWatch({
		control,
		name: "friendly_name"
	});
	function getCookie(name) {
		let cookieValue = "";
		if (document.cookie && document.cookie !== "") {
			const cookies = document.cookie.split(";");
			for (let i = 0; i < cookies.length; i++) {
				const cookie = cookies[i].trim();
				if (cookie.substring(0, name.length + 1) === name + "=") {
					cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
					break;
				}
			}
		}
		return cookieValue;
	}
	const onSubmit = (data) => {
		fetch("/rest/rooms", {
			credentials: "same-origin",
			method: "PUT",
			mode: "same-origin",
			headers: {
				"Content-Type": "application/json",
				"X-CSRFToken": getCookie("csrftoken")
			},
			body: JSON.stringify(data)
		}).then(async (response) => {
			const data = await response.json();
			if (!response.ok) {
				const error = data && data.message || response.status;
				return Promise.reject(error);
			}
			Notify({
				message: `Saved room setting successfully.`,
				level: "success",
				duration: 5e3
			});
		}).catch((error) => {
			Notify({
				message: `Error saving entity. Error: ${error}`,
				level: "error",
				duration: 1e4
			});
		});
	};
	const deleteRoom = () => {
		fetch(`/rest/rooms/${room_id}`, {
			method: "DELETE",
			headers: { "X-CSRFToken": getCookie("csrftoken") }
		}).then(async (response) => {
			const data = await response.json();
			if (!response.ok) return Promise.reject(data && data.message || response.status);
			window.location.href = "/rooms";
		}).catch((error) => {
			delete_confirm_dialog_ref.current?.close();
			Notify({
				message: `Failed to delete room: ${error}`,
				level: "error",
				duration: 1e4
			});
		});
	};
	(0, import_react.useEffect)(() => {
		if (stompStatus == "none") useStompStore.getState().connect();
	}, [stompStatus]);
	(0, import_react.useEffect)(() => {
		if (entityStatus == "none") useEntityStatesStore.getState().fetchData();
	}, [entityStatus]);
	(0, import_react.useEffect)(() => {
		if (useAvailableEntitiesStore.getState().status == "none") useAvailableEntitiesStore.getState().fetchEntities();
	}, []);
	(0, import_react.useEffect)(() => {
		if (room && !hasLoadedValues) {
			reset({
				id: room.id,
				friendly_name: room.friendly_name,
				room_temp_provider: room.room_temp_provider,
				room_temp_sensor: room.room_temp_sensor
			});
			setHasLoadedValues(true);
		}
	}, [
		room,
		reset,
		hasLoadedValues,
		setHasLoadedValues
	]);
	if (entityStatus != "loaded") return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		className: "flex w-full items-center justify-center text-2xl",
		children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { className: "loading loading-spinner loading-sm mr-2" }), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
			className: "font-medium",
			children: [
				"Loading data (",
				entityStatus,
				")..."
			]
		})]
	});
	if (room_id && !rooms[room_id]) return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
		className: "flex w-full items-center justify-center text-2xl",
		children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
			className: "font-medium text-error text-lg",
			children: [
				"Room with ID ",
				room_id,
				" not found."
			]
		})
	});
	const classNames = {
		control: (state) => `${state.isFocused ? "border" : "border-0"} border-accent p-2.5 text-sm rounded-box bg-base-300 text-base-content rounded-md`,
		menu: () => "bg-base-300 p-2.5 rounded-box text-base-content",
		option: (state) => `p-1 ${state.isSelected ? "bg-primary/20 rounded-sm" : ""} ${state.isFocused ? "bg-primary/20 rounded-sm" : ""}`
	};
	const CustomOption = ({ innerProps, isDisabled, isFocused, isSelected, children, data }) => {
		if (isDisabled) return null;
		return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
			...innerProps,
			className: `p-1 ${isSelected ? "bg-primary/20 rounded-sm" : ""} ${isFocused ? "bg-primary/20 rounded-sm" : ""}`,
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { className: `mdi ${data.icon} me-2` }), children]
		});
	};
	const select_components = { Option: CustomOption };
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)(import_jsx_runtime.Fragment, { children: [
		/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("dialog", {
			ref: delete_confirm_dialog_ref,
			className: "modal",
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "modal-box",
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h3", {
						className: "text-lg font-bold",
						children: "Delete room"
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
						className: "py-4",
						children: [
							"Are you sure you want to delete room '",
							room.friendly_name,
							"'? Its entities, scenes and pages will be deleted. Any panels in it will be moved to another room."
						]
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "flex justify-end join",
						children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
							onClick: () => delete_confirm_dialog_ref.current?.close(),
							className: "btn btn-neutral join-item",
							children: "Cancel"
						}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
							onClick: deleteRoom,
							className: "btn btn-error join-item",
							children: "Delete"
						})]
					})
				]
			}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("form", {
				method: "dialog",
				className: "modal-backdrop",
				children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", { children: "close" })
			})]
		}),
		/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("form", {
			onSubmit: handleSubmit(onSubmit),
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "flex items-center justify-between",
				id: "nspanel_settings_container",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", { children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("h2", {
					className: "font-medium text-2xl",
					id: "nspanel_name",
					children: [
						"Settings for room '",
						current_friendly_name,
						"'"
					]
				}) }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("a", {
					href: "https://nspanelmanager.com/docs/web-interface#room-page",
					target: "_blank",
					className: "btn btn-outline btn-info",
					children: "Help"
				})]
			}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
				className: "md:flex md:justify-between md:items-start mt-2",
				children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "p-4 bg-base-100 rounded-md shadow-lg w-full",
					children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
							className: "block mb-2 text-xl",
							children: "General"
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
							className: "",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("label", {
								htmlFor: "friendly_name",
								className: "block mb-2 text-sm font-medium",
								children: "Name"
							}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
								className: "flex flex-row-reverse",
								children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
									className: "outline-none rounded-none bg-base-300 border-neutral rounded-e-md border border-l-0 focus:ring-0 focus:border-accent block flex-1 min-w-0 w-full text-sm p-2.5 peer/name",
									type: "text",
									...register("friendly_name")
								}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
									className: "inline-flex items-center px-3 text-sm border border-neutral rounded-e-0 rounded-s-md peer-focus/name:border-accent",
									children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)(import_Icon.Icon, {
										path: mdiTextShort,
										className: "w-4 h-4"
									}), " "]
								})]
							})]
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
							type: "hidden",
							name: "room_temp_provider",
							id: "room_temp_provider",
							readOnly: true,
							value: "{{ room.room_temp_provider }}"
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
							className: "my-2 w-full md:ms-1",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("label", {
								className: "block mb-2 text-sm font-medium",
								children: "Room temperature sensor"
							}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)(StateManagedSelect$1, {
								options: all_options,
								classNames,
								onChange: (newValue) => {
									if (newValue) {
										setValue("room_temp_provider", newValue.type, { shouldDirty: true });
										setValue("room_temp_sensor", newValue.value, { shouldDirty: true });
									} else {
										setValue("room_temp_provider", "", { shouldDirty: true });
										setValue("room_temp_sensor", "", { shouldDirty: true });
									}
								},
								unstyled: true,
								components: select_components,
								value: all_options.find((option) => option.value === getValues("room_temp_sensor")),
								styles: {
									input: (base) => ({
										...base,
										"input:focus": { boxShadow: "none" }
									}),
									multiValueLabel: (base) => ({
										...base,
										whiteSpace: "normal",
										overflow: "visible"
									}),
									control: (base) => ({
										...base,
										transition: "none"
									})
								}
							})]
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)(HomeAssistantAreaField, { roomId: room.id }),
						!can_delete && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
							role: "alert",
							className: "alert alert-info my-4",
							children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: "The last room cannot be deleted while panels are assigned to it. Create another room or remove the panels first." })
						}),
						/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
							className: "text-right mt-4",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								type: "button",
								className: "btn btn-error",
								disabled: !can_delete,
								onClick: () => delete_confirm_dialog_ref.current?.showModal(),
								children: "Delete"
							}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								type: "submit",
								className: "btn btn-success",
								children: "Save"
							})]
						})
					]
				})
			})]
		}),
		/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
			className: "md:flex md:justify-between md:items-start mt-2",
			children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
				className: "p-4 bg-base-100 rounded-md shadow-lg w-full",
				children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(EntitiesPagesView, {
					room_id: room.id,
					type: "scene"
				})
			})
		}),
		/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
			className: "md:flex md:justify-between md:items-start mt-2 mb-4",
			children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
				className: "p-4 bg-base-100 rounded-md shadow-lg w-full",
				children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(EntitiesPagesView, {
					room_id: room.id,
					type: "entity"
				})
			})
		})
	] });
}
//#endregion
export { RoomPage as default };
