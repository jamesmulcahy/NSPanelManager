import { r as require_react, t as require_jsx_runtime } from "./main-DUoJrAcm.js";
require_react();
var import_jsx_runtime = require_jsx_runtime();
function Card({ title, actions, children }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsxs)("section", {
		className: "p-4 mt-2 bg-base-100 rounded-box shadow-lg w-full",
		"aria-label": title,
		children: [/* @__PURE__ */ (0, import_jsx_runtime.jsxs)("div", {
			className: "flex items-center justify-between mb-2",
			children: [/* @__PURE__ */ (0, import_jsx_runtime.jsx)("h3", {
				className: "text-xl",
				children: title
			}), actions]
		}), children]
	});
}
function Row({ children }) {
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
		className: "flex flex-wrap md:flex-nowrap gap-2",
		children
	});
}
function Alert({ level, children }) {
	const className = {
		info: "alert-info",
		warning: "alert-warning",
		error: "alert-error"
	}[level];
	return /* @__PURE__ */ (0, import_jsx_runtime.jsx)("div", {
		role: level === "error" ? "alert" : "status",
		className: `alert ${className} my-2`,
		children: /* @__PURE__ */ (0, import_jsx_runtime.jsx)("span", { children })
	});
}
//#endregion
export { Card as n, Row as r, Alert as t };
