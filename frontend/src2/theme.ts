import { call } from 'frappe-ui'
import { ref } from 'vue'

// SAP Fiori theme: a per-user preference stored server-side (user defaults).
// Enabling toggles the `fiori-theme` class on <html>, which the CSS in
// index.css and the chart palette in charts/colors.ts key off.

export const fioriThemeEnabled = ref(false)

export function applyFioriTheme(enabled: boolean) {
	fioriThemeEnabled.value = enabled
	document.documentElement.classList.toggle('fiori-theme', enabled)
}

export async function loadFioriTheme() {
	try {
		const prefs = await call('insights.api.user.get_user_preferences')
		applyFioriTheme(Boolean(prefs?.fiori_theme))
	} catch (e) {
		// guest views (shared dashboards) have no user preferences
	}
}

export async function saveFioriTheme(enabled: boolean) {
	applyFioriTheme(enabled)
	await call('insights.api.user.set_fiori_theme', { enabled: enabled ? 1 : 0 })
}
