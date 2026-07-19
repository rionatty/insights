
export const COLOR_MAP = {
	blue: '#318AD8',
	pink: '#F683AE',
	green: '#48BB74',
	red: '#F56B6B',
	yellow: '#FACF7A',
	purple: '#44427B',
	teal: '#5FD8C4',
	orange: '#F8814F',
	cyan: '#15CCEF',
	grey: '#A6B1B9',
	'#449CF0': '#449CF0',
	'#ECAD4B': '#ECAD4B',
	'#761ACB': '#761ACB',
	'#CB2929': '#CB2929',
	'#ED6396': '#ED6396',
	'#29CD42': '#29CD42',
	'#4463F0': '#4463F0',
	'#EC864B': '#EC864B',
	'#4F9DD9': '#4F9DD9',
	'#39E4A5': '#39E4A5',
	'#B4CD29': '#B4CD29',
}

// SAP Fiori cockpit palette (per-user theme): light azure bars first, soft
// green as the second series, then supporting hues — matches the B1 Web
// Client charts. Used when the `fiori-theme` class is set on <html>.
export const FIORI_COLORS = [
	'#5CACE2',
	'#8FCC63',
	'#318AD8',
	'#F8814F',
	'#5FD8C4',
	'#FACF7A',
	'#F56B6B',
	'#44427B',
	'#F683AE',
	'#15CCEF',
	'#A6B1B9',
]

// https://10015.io/tools/color-shades-generator
export const GRADIENT_COLORS = {
	blue: ['#2d87d6', '#4393da', '#589fdf', '#6dace3', '#83b8e7', '#98c4eb', '#c3dcf3', '#d8e9f7', '#edf5fc', '#ffffff'],
}

const isFioriTheme = () =>
	typeof document !== 'undefined' && document.documentElement.classList.contains('fiori-theme')

export const getColors = () => {
	return isFioriTheme() ? FIORI_COLORS : Object.values(COLOR_MAP)
}

export const getGradientColors = (color: keyof typeof GRADIENT_COLORS) => {
	return GRADIENT_COLORS[color]
}
