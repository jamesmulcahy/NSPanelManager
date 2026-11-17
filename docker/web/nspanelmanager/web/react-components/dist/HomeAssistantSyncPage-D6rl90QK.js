import { c as __toESM, r as require_react, t as require_jsx_runtime } from "./main-DUoJrAcm.js";
import { t as api } from "./client-CRfCe5X7.js";
import { A as selectedRows, C as parseLabelIds, D as rowName, E as roomOptions, F as withIgnored, M as typeLabel, N as unsetRooms, O as selectAll, P as valueToChoice, S as nameErrors, T as restingAreas, _ as initialChoices, a as areasWithoutRoom, b as isSelectable, c as buildRoomsFromAreas, d as displayOrder, f as draftErrors, g as groupState, h as groupByRoom, i as areaOwners, j as toggleGroup, k as selectNone, l as choiceToValue, m as filterCandidates, n as NO_FILTERS, o as buildImportItems, p as errorMessage, r as applySuggestions, s as buildRoomLinks, t as ENTITY_TYPES, u as countByRoom, v as initialDrafts, w as pruneSelection, x as joinLabelIds, y as invertSelection } from "./sync-Dde6AJAS.js";
//#region src/components/HomeAssistantSyncPage/common.tsx
var import_react = /* @__PURE__ */ __toESM(require_react(), 1);
var import_jsx_runtime = require_jsx_runtime();
/** An error banner. Home Assistant failures are shown with the server's message, never as an empty list. */
function ErrorBanner({ message, onRetry }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		role: "alert",
		className: "alert alert-error my-2",
		children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: message }), onRetry && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
			type: "button",
			className: "btn btn-sm",
			onClick: onRetry,
			children: "Retry"
		})]
	});
}
function Loading({ text }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		className: "flex w-full items-center justify-center text-xl my-4",
		children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { className: "loading loading-spinner loading-sm mr-2" }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
			className: "font-medium",
			children: text
		})]
	});
}
//#endregion
//#region src/components/HomeAssistantSyncPage/useLoader.ts
/** Runs `load` on mount and whenever `reload()` is called. A failed load is an error state, not empty data. */
function useLoader(load, deps = []) {
	const [state, setState] = (0, import_react.useState)({ status: "loading" });
	const [generation, setGeneration] = (0, import_react.useState)(0);
	const reload = (0, import_react.useCallback)(() => setGeneration((value) => value + 1), []);
	(0, import_react.useEffect)(() => {
		let current = true;
		load().then((data) => current && setState({
			status: "loaded",
			data
		})).catch((error) => current && setState({
			status: "error",
			message: error instanceof Error ? error.message : String(error)
		}));
		return () => {
			current = false;
		};
	}, [generation, ...deps]);
	return {
		state,
		reload
	};
}
//#endregion
//#region src/components/HomeAssistantSyncPage/EntitiesStep.tsx
async function loadMeta() {
	const [links, labels, settings] = await Promise.all([
		api.GET("/rest/v2/home_assistant/room_links"),
		api.GET("/rest/v2/home_assistant/labels"),
		api.GET("/rest/v2/settings")
	]);
	if (!links.data) throw new Error(errorMessage(links.error, links.response));
	if (!labels.data) throw new Error(errorMessage(labels.error, labels.response));
	if (!settings.data) throw new Error(errorMessage(settings.error, settings.response));
	return {
		rooms: links.data,
		labels: labels.data,
		excluded: parseLabelIds(settings.data.home_assistant_sync_exclude_labels)
	};
}
function GroupCheckbox({ state, label, onChange }) {
	const ref = (0, import_react.useRef)(null);
	(0, import_react.useEffect)(() => {
		if (ref.current) ref.current.indeterminate = state === "some";
	}, [state]);
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
		ref,
		type: "checkbox",
		className: "checkbox checkbox-sm",
		"aria-label": label,
		checked: state === "all",
		onChange
	});
}
function EntitiesStep({ onShowRooms }) {
	const [includeHidden, setIncludeHidden] = (0, import_react.useState)(false);
	const [includeImported, setIncludeImported] = (0, import_react.useState)(false);
	const [includeGroups, setIncludeGroups] = (0, import_react.useState)(false);
	const [filters, setFilters] = (0, import_react.useState)(NO_FILTERS);
	const [selected, setSelected] = (0, import_react.useState)(/* @__PURE__ */ new Set());
	const [names, setNames] = (0, import_react.useState)({});
	const [confirming, setConfirming] = (0, import_react.useState)(false);
	const [importing, setImporting] = (0, import_react.useState)(false);
	const [importError, setImportError] = (0, import_react.useState)(null);
	const [summary, setSummary] = (0, import_react.useState)(null);
	const [labelDraft, setLabelDraft] = (0, import_react.useState)(null);
	const [labelError, setLabelError] = (0, import_react.useState)(null);
	const meta = useLoader(loadMeta);
	const candidatesLoader = useLoader(async () => {
		const { data, error, response } = await api.GET("/rest/v2/home_assistant/entity_candidates", { params: { query: {
			include_hidden: includeHidden,
			include_imported: includeImported,
			include_groups: includeGroups
		} } });
		if (!data) throw new Error(errorMessage(error, response));
		return data;
	}, [
		includeHidden,
		includeImported,
		includeGroups
	]);
	const loaded = candidatesLoader.state.status === "loaded" ? candidatesLoader.state.data : null;
	const candidates = loaded?.candidates ?? [];
	const [seenCandidates, setSeenCandidates] = (0, import_react.useState)(loaded);
	if (seenCandidates !== loaded) {
		setSeenCandidates(loaded);
		if (loaded) setSelected(pruneSelection(loaded.candidates, selected));
	}
	const visible = displayOrder(filterCandidates(candidates, filters));
	const groups = groupByRoom(visible);
	const chosen = selectedRows(candidates, selected);
	const hiddenSelected = chosen.filter((row) => !visible.includes(row)).length;
	const problems = nameErrors(candidates, selected, names);
	const metaData = meta.state.status === "loaded" ? meta.state.data : null;
	const roomName = (roomId) => metaData?.rooms.find((room) => room.room_id === roomId)?.name ?? candidates.find((row) => row.room_id === roomId)?.room_name ?? "another room";
	const linkedRooms = metaData?.rooms.filter((room) => room.link === "linked").length ?? 0;
	async function saveLabels() {
		if (!labelDraft) return;
		setLabelError(null);
		try {
			const { data, error, response } = await api.PATCH("/rest/v2/settings", { body: { home_assistant_sync_exclude_labels: joinLabelIds(labelDraft) } });
			if (!data) {
				setLabelError(`Couldn't save the excluded labels: ${errorMessage(error, response)}`);
				return;
			}
			setLabelDraft(null);
			meta.reload();
			candidatesLoader.reload();
		} catch (caught) {
			setLabelError(errorMessage(caught));
		}
	}
	async function runImport() {
		const items = buildImportItems(candidates, selected, names);
		const perRoom = countByRoom(candidates, selected);
		setImporting(true);
		setImportError(null);
		try {
			const { data, error, response } = await api.POST("/rest/v2/home_assistant/import", { body: { items } });
			setConfirming(false);
			if (!data) {
				setImportError(`Import failed: ${errorMessage(error, response)}`);
				return;
			}
			setSummary({
				result: data,
				perRoom
			});
			setSelected(/* @__PURE__ */ new Set());
			candidatesLoader.reload();
		} catch (caught) {
			setConfirming(false);
			setImportError(`Import failed: ${errorMessage(caught)}`);
		} finally {
			setImporting(false);
		}
	}
	if (meta.state.status === "loading") return /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Loading, { text: "Loading rooms..." });
	if (meta.state.status === "error") return /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ErrorBanner, {
		message: `Couldn't load from Home Assistant: ${meta.state.message}`,
		onRetry: meta.reload
	});
	if (linkedRooms === 0) return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
		className: "p-4 bg-base-100 rounded-md shadow-lg",
		children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", { children: [
			"No rooms are linked to a Home Assistant area yet.",
			" ",
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
				type: "button",
				className: "link",
				onClick: onShowRooms,
				children: "Link rooms in step 1"
			}),
			" ",
			"first."
		] })
	});
	const { labels, excluded } = meta.state.data;
	const labelValue = labelDraft ?? excluded;
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		className: "space-y-3",
		children: [
			summary && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				role: "status",
				className: "alert alert-success flex-col items-start",
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("strong", { children: [
						"Imported ",
						summary.result.created.length,
						" entit",
						summary.result.created.length === 1 ? "y" : "ies",
						summary.result.pages_added > 0 ? `, adding ${summary.result.pages_added} page${summary.result.pages_added === 1 ? "" : "s"}` : "",
						"."
					] }),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", { children: countCreated(summary).map((entry) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", { children: [
						entry.roomName,
						": ",
						entry.count,
						" created"
					] }, entry.roomId)) }),
					summary.result.skipped.length > 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: ["Skipped:", /* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", { children: summary.result.skipped.map((skip) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", { children: [
						skip.entity_id,
						": ",
						skip.reason === "already_imported" ? "already imported" : skip.reason
					] }, skip.entity_id)) })] }),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						className: "btn btn-sm",
						onClick: () => setSummary(null),
						children: "Dismiss"
					})
				]
			}),
			importError && /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ErrorBanner, { message: importError }),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				className: "p-4 bg-base-100 rounded-md shadow-lg space-y-3",
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "flex flex-wrap items-center gap-2",
						children: [
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
								className: "join",
								children: [
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
										type: "button",
										className: "btn btn-sm join-item",
										onClick: () => setSelected((current) => selectAll(current, visible)),
										children: "Select all"
									}),
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
										type: "button",
										className: "btn btn-sm join-item",
										onClick: () => setSelected((current) => selectNone(current, visible)),
										children: "Select none"
									}),
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
										type: "button",
										className: "btn btn-sm join-item",
										onClick: () => setSelected((current) => invertSelection(current, visible)),
										children: "Invert selection"
									})
								]
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("select", {
								className: "select select-bordered select-sm",
								"aria-label": "Filter by type",
								value: filters.type,
								onChange: (event) => setFilters({
									...filters,
									type: event.target.value
								}),
								children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
									value: "all",
									children: "All types"
								}), ENTITY_TYPES.map((type) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
									value: type.value,
									children: type.label
								}, type.value))]
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("select", {
								className: "select select-bordered select-sm",
								"aria-label": "Filter by room",
								value: String(filters.roomId),
								onChange: (event) => setFilters({
									...filters,
									roomId: event.target.value === "all" ? "all" : Number(event.target.value)
								}),
								children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
									value: "all",
									children: "All rooms"
								}), roomOptions(candidates).map((room) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
									value: room.roomId,
									children: room.roomName
								}, room.roomId))]
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
								className: "ml-auto font-medium",
								"aria-live": "polite",
								children: [
									chosen.length,
									" selected",
									hiddenSelected > 0 ? ` (${hiddenSelected} hidden by filters)` : ""
								]
							})
						]
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "flex flex-wrap items-center gap-4",
						children: [
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
								className: "label cursor-pointer gap-2",
								children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
									type: "checkbox",
									className: "toggle toggle-sm",
									checked: includeHidden,
									onChange: (event) => setIncludeHidden(event.target.checked)
								}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: "Show hidden" })]
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
								className: "label cursor-pointer gap-2",
								children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
									type: "checkbox",
									className: "toggle toggle-sm",
									checked: includeImported,
									onChange: (event) => setIncludeImported(event.target.checked)
								}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: "Show already imported" })]
							}),
							/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
								className: "label cursor-pointer gap-2",
								children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
									type: "checkbox",
									className: "toggle toggle-sm",
									checked: includeGroups,
									onChange: (event) => setIncludeGroups(event.target.checked)
								}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: "Show light groups" })]
							})
						]
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("details", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("summary", {
						className: "cursor-pointer",
						children: [
							"Excluded labels (",
							excluded.length,
							")"
						]
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "mt-2 space-y-1",
						children: [
							labels.length === 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
								className: "text-base-content/70",
								children: "Home Assistant has no labels."
							}),
							labels.map((label) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("label", {
								className: "flex items-center gap-2",
								children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
									type: "checkbox",
									className: "checkbox checkbox-sm",
									checked: labelValue.includes(label.label_id),
									onChange: (event) => setLabelDraft(event.target.checked ? [...labelValue, label.label_id] : labelValue.filter((id) => id !== label.label_id))
								}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: label.name })]
							}, label.label_id)),
							labelValue.filter((id) => !labels.some((label) => label.label_id === id)).map((id) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
								className: "text-sm text-base-content/70",
								children: [
									"Excluded label ",
									id,
									" no longer exists in Home Assistant."
								]
							}, id)),
							labelError && /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ErrorBanner, { message: labelError }),
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								type: "button",
								className: "btn btn-sm btn-info",
								disabled: labelDraft === null,
								onClick: saveLabels,
								children: "Save excluded labels"
							})
						]
					})] }),
					loaded && loaded.entities_without_area > 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
						className: "text-sm text-base-content/70",
						children: [
							loaded.entities_without_area,
							" supported ",
							loaded.entities_without_area === 1 ? "entity has" : "entities have",
							" no area in Home Assistant — assign an area there to import them."
						]
					}),
					loaded && loaded.excluded_by_label > 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("p", {
						className: "text-sm text-base-content/70",
						children: [
							loaded.excluded_by_label,
							" ",
							loaded.excluded_by_label === 1 ? "entity is" : "entities are",
							" left out because of an excluded label."
						]
					})
				]
			}),
			candidatesLoader.state.status === "loading" && /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Loading, { text: "Loading entities from Home Assistant..." }),
			candidatesLoader.state.status === "error" && /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ErrorBanner, {
				message: `Couldn't load entities: ${candidatesLoader.state.message}`,
				onRetry: candidatesLoader.reload
			}),
			loaded && groups.length === 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
				className: "p-4 bg-base-100 rounded-md shadow-lg text-base-content/70",
				children: "Nothing to import."
			}),
			loaded && groups.length > 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
				className: "overflow-x-auto bg-base-100 rounded-md shadow-lg",
				children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("table", {
					className: "table table-sm",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("thead", { children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("tr", { children: [
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("th", { className: "w-8" }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("th", { children: "Name" }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("th", { children: "Home Assistant entity" }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("th", { children: "Type" }),
						/* @__PURE__ */ (0, import_jsx_runtime.jsx)("th", { children: "Room" })
					] }) }), groups.map((group) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("tbody", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("tr", {
						className: "bg-base-200",
						children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("td", { children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)(GroupCheckbox, {
							state: groupState(selected, group.rows),
							label: `Select all in ${group.roomName}`,
							onChange: () => setSelected((current) => toggleGroup(current, group.rows))
						}) }), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("th", {
							colSpan: 4,
							children: [
								group.roomName,
								" (",
								group.rows.length,
								")"
							]
						})]
					}), group.rows.map((row) => {
						const selectable = isSelectable(row);
						return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("tr", {
							className: selectable ? "" : "opacity-60",
							children: [
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("td", { children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
									type: "checkbox",
									className: "checkbox checkbox-sm",
									"aria-label": `Select ${row.entity_id}`,
									disabled: !selectable,
									checked: selectable && selected.has(row.entity_id),
									onChange: (event) => setSelected((current) => {
										const next = new Set(current);
										if (event.target.checked) next.add(row.entity_id);
										else next.delete(row.entity_id);
										return next;
									})
								}) }),
								/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("td", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
									type: "text",
									className: `input input-bordered input-sm w-full ${problems[row.entity_id] ? "input-error" : ""}`,
									"aria-label": `Name for ${row.entity_id}`,
									value: rowName(row, names),
									disabled: !selectable,
									onChange: (event) => setNames({
										...names,
										[row.entity_id]: event.target.value
									})
								}), problems[row.entity_id] && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
									className: "text-xs text-error",
									children: problems[row.entity_id]
								})] }),
								/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("td", { children: [
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", { children: row.entity_id }),
									/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
										className: "text-xs text-base-content/70",
										children: row.ha_name
									}),
									(row.hidden || row.is_group) && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
										className: "text-xs text-base-content/70",
										children: [row.hidden ? "hidden" : "", row.is_group ? "light group" : ""].filter(Boolean).join(", ")
									})
								] }),
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("td", { children: typeLabel(row.entity_type) }),
								/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("td", { children: [row.room_name, !selectable && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
									className: "text-xs",
									children: ["Already imported in ", roomName(row.already_imported_room_id)]
								})] })
							]
						}, row.entity_id);
					})] }, group.roomId))]
				})
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
				className: "text-right",
				children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("button", {
					type: "button",
					className: "btn btn-success",
					disabled: chosen.length === 0 || Object.keys(problems).length > 0 || importing,
					onClick: () => setConfirming(true),
					children: ["Import ", chosen.length]
				})
			}),
			confirming && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
				role: "dialog",
				"aria-label": "Confirm import",
				className: "p-4 bg-base-100 rounded-md shadow-lg border border-accent",
				children: [
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("h3", {
						className: "text-lg font-semibold",
						children: [
							"Import ",
							chosen.length,
							" entit",
							chosen.length === 1 ? "y" : "ies",
							"?"
						]
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
						className: "my-2",
						children: countByRoom(candidates, selected).map((entry) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", { children: [
							entry.roomName,
							": ",
							entry.count
						] }, entry.roomId))
					}),
					/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
						className: "flex justify-end gap-2",
						children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
							type: "button",
							className: "btn btn-neutral",
							onClick: () => setConfirming(false),
							children: "Cancel"
						}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
							type: "button",
							className: "btn btn-success",
							disabled: importing,
							onClick: runImport,
							children: "Confirm import"
						})]
					})
				]
			})
		]
	});
}
/** Created entities per room, named from the summary taken when the import started. */
function countCreated(summary) {
	const counts = /* @__PURE__ */ new Map();
	for (const created of summary.result.created) counts.set(created.room_id, (counts.get(created.room_id) ?? 0) + 1);
	return [...counts].map(([roomId, count]) => ({
		roomId,
		count,
		roomName: summary.perRoom.find((entry) => entry.roomId === roomId)?.roomName ?? `Room ${roomId}`
	}));
}
//#endregion
//#region src/components/HomeAssistantSyncPage/RoomsStep.tsx
async function loadRooms() {
	const [links, areas] = await Promise.all([api.GET("/rest/v2/home_assistant/room_links"), api.GET("/rest/v2/home_assistant/areas")]);
	if (!links.data) throw new Error(errorMessage(links.error, links.response));
	if (!areas.data) throw new Error(errorMessage(areas.error, areas.response));
	return {
		rows: links.data,
		areas: areas.data
	};
}
function RoomsStep({ onRoomsChanged }) {
	const { state, reload } = useLoader(loadRooms);
	if (state.status === "loading") return /* @__PURE__ */ (0, import_jsx_runtime.jsx)(Loading, { text: "Loading rooms and areas from Home Assistant..." });
	if (state.status === "error") return /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ErrorBanner, {
		message: `Couldn't load rooms and areas: ${state.message}`,
		onRetry: reload
	});
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)(RoomsForm, {
		data: state.data,
		reload,
		onRoomsChanged
	});
}
function RoomsForm({ data, reload, onRoomsChanged }) {
	const { rows, areas } = data;
	const [choices, setChoices] = (0, import_react.useState)(() => initialChoices(rows));
	const [drafts, setDrafts] = (0, import_react.useState)(() => initialDrafts(areas));
	const [error, setError] = (0, import_react.useState)(null);
	const [notice, setNotice] = (0, import_react.useState)(null);
	const [busy, setBusy] = (0, import_react.useState)(false);
	const [showErrors, setShowErrors] = (0, import_react.useState)(false);
	const [seen, setSeen] = (0, import_react.useState)(data);
	if (seen !== data) {
		setSeen(data);
		const next = initialChoices(rows);
		for (const row of unsetRooms(rows)) if (row.room_id in choices) next[row.room_id] = choices[row.room_id];
		setChoices(next);
		setDrafts(initialDrafts(areas, drafts));
	}
	const unset = unsetRooms(rows);
	const areaName = (areaId) => areas.find((area) => area.area_id === areaId)?.name ?? areaId;
	const decisions = buildRoomLinks(rows, choices);
	const missing = rows.filter((row) => row.link === "linked" && row.area_missing);
	const withoutRoom = areasWithoutRoom(areas);
	const resting = restingAreas(areas);
	const errors = draftErrors(areas, drafts);
	const checkedDrafts = buildRoomsFromAreas(areas, drafts);
	async function run(action) {
		setBusy(true);
		setError(null);
		setNotice(null);
		try {
			const result = await action();
			if (result.ok) {
				setNotice(result.message);
				reload();
				onRoomsChanged?.();
			} else setError(result.message);
		} catch (caught) {
			setError(errorMessage(caught));
		} finally {
			setBusy(false);
		}
	}
	const saveRooms = () => run(async () => {
		const { data: saved, error: failure, response } = await api.PUT("/rest/v2/home_assistant/room_links", { body: decisions });
		return saved ? {
			ok: true,
			message: `Saved ${saved.length} room${saved.length === 1 ? "" : "s"}.`
		} : {
			ok: false,
			message: `Couldn't save the rooms: ${errorMessage(failure, response)}`
		};
	});
	const setIgnored = (ids, message) => run(async () => {
		const { data: saved, error: failure, response } = await api.PUT("/rest/v2/home_assistant/ignored_areas", { body: { area_ids: ids } });
		return saved ? {
			ok: true,
			message
		} : {
			ok: false,
			message: `Couldn't save the ignored areas: ${errorMessage(failure, response)}`
		};
	});
	const createRooms = () => {
		setShowErrors(true);
		if (Object.keys(errors).length > 0 || checkedDrafts.length === 0) return;
		setShowErrors(false);
		return run(async () => {
			const { data: created, error: failure, response } = await api.POST("/rest/v2/home_assistant/rooms_from_areas", { body: checkedDrafts });
			return created ? {
				ok: true,
				message: `Created ${created.length} room${created.length === 1 ? "" : "s"}.`
			} : {
				ok: false,
				message: `Couldn't create the rooms: ${errorMessage(failure, response)}`
			};
		});
	};
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
		className: "space-y-4",
		children: [
			error && /* @__PURE__ */ (0, import_jsx_runtime.jsx)(ErrorBanner, { message: error }),
			notice && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
				role: "status",
				className: "alert alert-success my-2",
				children: notice
			}),
			missing.length > 0 && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
				role: "alert",
				className: "alert alert-warning",
				children: /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", { children: [
					"Area missing in Home Assistant: ",
					missing.map((row) => `${row.name} (was ${row.area_id})`).join(", "),
					". The rooms stay linked; relink them on their room page."
				] })
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: "p-4 bg-base-100 rounded-md shadow-lg",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "flex items-center justify-between mb-2",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h3", {
						className: "text-xl",
						children: "Rooms without a Home Assistant area"
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						className: "btn btn-outline btn-sm",
						disabled: unset.length === 0 || busy,
						onClick: () => setChoices((current) => applySuggestions(rows, current)),
						children: "Apply all suggestions"
					})]
				}), unset.length === 0 ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
					className: "text-base-content/70",
					children: "Every room has been linked or marked as having no association."
				}) : /* @__PURE__ */ (0, import_jsx_runtime.jsxs)(import_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
					className: "space-y-2",
					children: unset.map((row) => {
						const owners = areaOwners(rows, areas, choices, row.room_id);
						const choice = choices[row.room_id] ?? valueToChoice("");
						return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", {
							className: "flex flex-wrap items-center gap-2",
							children: [
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
									className: "w-48 font-medium",
									children: row.name
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("select", {
									className: "select select-bordered select-sm",
									"aria-label": `Area for ${row.name}`,
									value: choiceToValue(choice),
									onChange: (event) => setChoices({
										...choices,
										[row.room_id]: valueToChoice(event.target.value)
									}),
									children: [
										/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
											value: "",
											children: "Skip for now"
										}),
										/* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
											value: choiceToValue({ kind: "none" }),
											children: "No association"
										}),
										areas.map((area) => /* @__PURE__ */ (0, import_jsx_runtime.jsx)("option", {
											value: area.area_id,
											disabled: area.area_id in owners,
											children: area.area_id in owners ? `${area.name} (used by ${owners[area.area_id]})` : area.name
										}, area.area_id))
									]
								}),
								row.suggestion_ambiguous && /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("span", {
									className: "text-sm text-warning",
									children: ["Could be: ", row.suggestion_candidates.map(areaName).join(", ")]
								})
							]
						}, row.room_id);
					})
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
					className: "text-right mt-4",
					children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						className: "btn btn-success",
						disabled: decisions.length === 0 || busy,
						onClick: saveRooms,
						children: "Save"
					})
				})] })]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
				className: "p-4 bg-base-100 rounded-md shadow-lg",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h3", {
					className: "text-xl mb-2",
					children: "Home Assistant areas without a room"
				}), withoutRoom.length === 0 ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
					className: "text-base-content/70",
					children: "Every area has a room or has been dismissed."
				}) : /* @__PURE__ */ (0, import_jsx_runtime.jsxs)(import_jsx_runtime.Fragment, { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
					className: "space-y-2",
					children: withoutRoom.map((area) => {
						const draft = drafts[area.area_id] ?? {
							areaId: area.area_id,
							name: area.name,
							checked: false
						};
						const problem = draft.checked || showErrors ? errors[area.area_id] : void 0;
						return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", {
							className: "flex flex-wrap items-center gap-2",
							children: [
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
									type: "checkbox",
									className: "checkbox checkbox-sm",
									"aria-label": `Create a room for ${area.name}`,
									checked: draft.checked,
									onChange: (event) => setDrafts({
										...drafts,
										[area.area_id]: {
											...draft,
											checked: event.target.checked
										}
									})
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("input", {
									type: "text",
									className: `input input-bordered input-sm ${problem ? "input-error" : ""}`,
									"aria-label": `Room name for ${area.name}`,
									maxLength: 30,
									value: draft.name,
									onChange: (event) => setDrafts({
										...drafts,
										[area.area_id]: {
											...draft,
											name: event.target.value
										}
									})
								}),
								problem && /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
									className: "text-sm text-error",
									children: problem
								}),
								/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
									type: "button",
									className: "btn btn-ghost btn-sm",
									disabled: busy,
									onClick: () => setIgnored(withIgnored(areas, { add: [area.area_id] }), `Won't ask about ${area.name} again.`),
									children: "Don't ask again"
								})
							]
						}, area.area_id);
					})
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
					className: "text-right mt-4",
					children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
						type: "button",
						className: "btn btn-success",
						disabled: checkedDrafts.length === 0 || busy,
						onClick: createRooms,
						children: "Create rooms"
					})
				})] })]
			}),
			/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("details", {
				className: "p-4 bg-base-100 rounded-md shadow-lg",
				children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("summary", {
					className: "cursor-pointer text-xl",
					children: [
						"Linked / no association / ignored areas (",
						rows.filter((row) => row.link !== "unset").length + resting.filter((area) => area.ignored).length,
						")"
					]
				}), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
					className: "mt-2 space-y-4",
					children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h4", {
						className: "font-medium",
						children: "Rooms"
					}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
						className: "space-y-1",
						children: rows.filter((row) => row.link !== "unset").map((row) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", { children: [
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)("a", {
								className: "link",
								href: `/rooms/${row.room_id}/`,
								children: row.name
							}),
							" ",
							/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", {
								className: "text-base-content/70",
								children: row.link === "none" ? "No association" : row.area_missing ? `Area missing in Home Assistant (${row.area_id})` : `Linked to ${row.area_name ?? row.area_id}`
							})
						] }, row.room_id))
					})] }), /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h4", {
						className: "font-medium",
						children: "Ignored areas"
					}), resting.filter((area) => area.ignored).length === 0 ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)("p", {
						className: "text-base-content/70",
						children: "None."
					}) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)("ul", {
						className: "space-y-1",
						children: resting.filter((area) => area.ignored).map((area) => /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("li", {
							className: "flex items-center gap-2",
							children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children: area.name }), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
								type: "button",
								className: "btn btn-ghost btn-xs",
								disabled: busy,
								onClick: () => setIgnored(withIgnored(areas, { remove: [area.area_id] }), `${area.name} is offered as a new room again.`),
								children: "Stop ignoring"
							})]
						}, area.area_id))
					})] })]
				})]
			})
		]
	});
}
//#endregion
//#region src/components/HomeAssistantSyncPage/HomeAssistantSyncPage.tsx
function HomeAssistantSyncPage() {
	const [step, setStep] = (0, import_react.useState)("rooms");
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", { children: [
		/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
			className: "flex items-center justify-between",
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h2", {
				className: "text-2xl",
				children: "Sync from Home Assistant"
			}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("a", {
				href: "/rooms",
				className: "btn btn-outline btn-info",
				children: "Back to rooms"
			})]
		}),
		/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
			role: "tablist",
			className: "tabs tabs-bordered my-3",
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
				type: "button",
				role: "tab",
				"aria-selected": step === "rooms",
				className: `tab ${step === "rooms" ? "tab-active" : ""}`,
				onClick: () => setStep("rooms"),
				children: "1. Rooms"
			}), /* @__PURE__ */ (0, import_jsx_runtime.jsx)("button", {
				type: "button",
				role: "tab",
				"aria-selected": step === "entities",
				className: `tab ${step === "entities" ? "tab-active" : ""}`,
				onClick: () => setStep("entities"),
				children: "2. Entities"
			})]
		}),
		step === "rooms" ? /* @__PURE__ */ (0, import_jsx_runtime.jsx)(RoomsStep, {}) : /* @__PURE__ */ (0, import_jsx_runtime.jsx)(EntitiesStep, { onShowRooms: () => setStep("rooms") })
	] });
}
//#endregion
export { HomeAssistantSyncPage as default };
