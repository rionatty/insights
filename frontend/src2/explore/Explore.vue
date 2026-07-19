<script setup lang="ts">
import { watchDebounced } from '@vueuse/core'
import { Breadcrumbs, Button, Dialog, FormControl, call } from 'frappe-ui'
import {
	BarChart3,
	Calendar,
	Columns3,
	GripVertical,
	Hash,
	LoaderCircle,
	Rows3,
	Save,
	Sigma,
	SlidersHorizontal,
	Sparkles,
	Table2,
	Type,
	X,
} from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import draggable from 'vuedraggable'
import BaseChart from '../charts/components/BaseChart.vue'
import { getBarChartOptions, getLineChartOptions, guessChart } from '../charts/helpers'
import useDataSourceStore from '../data_source/data_source'
import { getTables } from '../data_source/tables'
import { showErrorToast } from '../helpers'
import { createToast } from '../helpers/toasts'
import { __ } from '../translation'

type Field = {
	id: string
	column_name: string
	data_type: string
	granularity?: string
	aggregation?: string
	operator?: string
	value?: string
}

const dataSourceStore = useDataSourceStore()
const selectedSource = ref('')
const selectedTable = ref('')
const tables = ref<{ table_name: string }[]>([])
const fields = ref<Field[]>([])

const rowsZone = ref<Field[]>([])
const columnsZone = ref<Field[]>([])
const valuesZone = ref<Field[]>([])
const filtersZone = ref<Field[]>([])

const sourceOptions = computed(() => [
	{ label: __('Select data source...'), value: '' },
	...dataSourceStore.sources.map((s) => ({ label: s.title, value: s.name })),
])
const tableOptions = computed(() => [
	{ label: __('Select table...'), value: '' },
	...tables.value.map((t) => ({ label: t.table_name, value: t.table_name })),
])

watch(selectedSource, async (source) => {
	selectedTable.value = ''
	tables.value = []
	if (source) {
		tables.value = await getTables(source, undefined, 500)
	}
})

watch(selectedTable, async (table) => {
	fields.value = []
	rowsZone.value = []
	columnsZone.value = []
	valuesZone.value = []
	filtersZone.value = []
	results.value = null
	if (!table) return
	const columns = await call('insights.api.data_sources.get_data_source_table_columns', {
		data_source: selectedSource.value,
		table_name: table,
	})
	fields.value = columns.map((c: any) => ({
		id: c.column,
		column_name: c.column,
		data_type: c.type,
	}))
	runExploration()
})

const isNumeric = (t: string) => ['Integer', 'Decimal'].includes(t)
const isTemporal = (t: string) => ['Date', 'Datetime', 'Time'].includes(t)

function fieldIcon(data_type: string) {
	if (isNumeric(data_type)) return Hash
	if (isTemporal(data_type)) return Calendar
	return Type
}

let dropCount = 0
function cloneField(field: Field): Field {
	return { ...field, id: `${field.column_name}-${dropCount++}` }
}

// give freshly dropped chips sensible defaults for their zone
watch(
	valuesZone,
	(items) => {
		for (const item of items) {
			if (!item.aggregation) {
				item.aggregation = isNumeric(item.data_type) ? 'sum' : 'count'
			}
		}
	},
	{ deep: true },
)
watch(
	[rowsZone, columnsZone],
	() => {
		for (const item of [...rowsZone.value, ...columnsZone.value]) {
			if (isTemporal(item.data_type) && !item.granularity) {
				item.granularity = 'month'
			}
		}
	},
	{ deep: true },
)
watch(
	filtersZone,
	(items) => {
		for (const item of items) {
			if (!item.operator) {
				item.operator = isNumeric(item.data_type) || isTemporal(item.data_type) ? '>=' : 'contains'
				item.value = item.value ?? ''
			}
		}
	},
	{ deep: true },
)

const aggregationOptions = [
	{ label: __('Sum'), value: 'sum' },
	{ label: __('Average'), value: 'avg' },
	{ label: __('Min'), value: 'min' },
	{ label: __('Max'), value: 'max' },
	{ label: __('Count'), value: 'count' },
	{ label: __('Distinct Count'), value: 'count_distinct' },
]
const granularityOptions = ['year', 'quarter', 'month', 'week', 'day'].map((g) => ({
	label: __(g.charAt(0).toUpperCase() + g.slice(1)),
	value: g,
}))
const operatorOptions = ['contains', '=', '!=', '>', '>=', '<', '<='].map((o) => ({
	label: o,
	value: o,
}))

function removeFrom(zone: Field[], item: Field) {
	zone.splice(zone.indexOf(item), 1)
}

function measureName(item: Field) {
	const agg = aggregationOptions.find((a) => a.value === item.aggregation)?.label || item.aggregation
	return `${item.column_name} (${agg})`
}

function buildOperations() {
	const ops: any[] = [
		{
			type: 'source',
			table: {
				type: 'table',
				data_source: selectedSource.value,
				table_name: selectedTable.value,
			},
		},
	]

	const rules = filtersZone.value
		.filter((f) => f.value !== '' && f.value != null)
		.map((f) => ({
			column: { type: 'column', column_name: f.column_name },
			operator: f.operator,
			value: isNumeric(f.data_type) ? Number(f.value) : f.value,
		}))
	if (rules.length) {
		ops.push({ type: 'filter_group', logical_operator: 'And', filters: rules })
	}

	const toDimension = (r: Field) => ({
		dimension_name: r.column_name,
		column_name: r.column_name,
		data_type: r.data_type,
		...(isTemporal(r.data_type) ? { granularity: r.granularity } : {}),
	})
	const dimensions = rowsZone.value.map(toDimension)
	const columnDims = columnsZone.value.map(toDimension)
	const measures = valuesZone.value.map((v) => ({
		measure_name: measureName(v),
		column_name: v.column_name,
		data_type: isNumeric(v.data_type) ? v.data_type : 'Integer',
		aggregation: v.aggregation,
	}))

	if (columnDims.length && measures.length) {
		// two-axis pivot: rows down, column values across
		ops.push({
			type: 'pivot_wider',
			rows: dimensions,
			columns: columnDims,
			values: measures,
			max_column_values: 10,
		})
	} else if (dimensions.length || measures.length) {
		ops.push({ type: 'summarize', measures, dimensions })
		if (measures.length) {
			ops.push({
				type: 'order_by',
				column: { type: 'column', column_name: measures[0].measure_name },
				direction: 'desc',
			})
		}
	}
	return ops
}

const results = ref<{ columns: any[]; rows: any[]; time_taken: number } | null>(null)
const running = ref(false)

async function runExploration() {
	if (!selectedTable.value) return
	running.value = true
	aiSQL.value = ''
	try {
		results.value = await call('insights.api.explore.run_exploration', {
			operations: JSON.stringify(buildOperations()),
			limit: 500,
		})
	} catch (e: any) {
		showErrorToast(e)
	} finally {
		running.value = false
	}
}

// ---- ask the AI ----
const question = ref('')
const asking = ref(false)
const aiSQL = ref('')

async function askAI() {
	if (!selectedSource.value || !question.value.trim()) return
	asking.value = true
	try {
		const response = await call('insights.api.ai.ask', {
			data_source: selectedSource.value,
			question: question.value,
		})
		aiSQL.value = response.sql
		results.value = {
			columns: response.columns,
			rows: response.rows,
			time_taken: response.time_taken,
		}
		viewMode.value = 'table'
	} catch (e: any) {
		showErrorToast(e)
	} finally {
		asking.value = false
	}
}

watchDebounced([rowsZone, columnsZone, valuesZone, filtersZone], () => runExploration(), {
	deep: true,
	debounce: 500,
})

// ---- auto chart ----
const viewMode = ref<'table' | 'chart'>('table')

const chartGuess = computed(() => {
	if (!results.value || columnsZone.value.length) return null
	if (!rowsZone.value.length || !valuesZone.value.length) return null
	const guess = guessChart(results.value.columns as any, results.value.rows)
	return guess === 'bar' || guess === 'line' ? guess : null
})

// prefer the chart the moment one becomes possible, drop back when it isn't
watch(chartGuess, (guess, previous) => {
	if (guess && !previous) viewMode.value = 'chart'
	if (!guess) viewMode.value = 'table'
})

const chartOptions = computed(() => {
	if (!results.value || !chartGuess.value) return null
	const first = rowsZone.value[0]
	const config = {
		x_axis: {
			dimension: {
				dimension_name: first.column_name,
				column_name: first.column_name,
				data_type: first.data_type,
				...(isTemporal(first.data_type) ? { granularity: first.granularity } : {}),
			},
		},
		y_axis: {
			series: valuesZone.value.map((v) => ({
				measure: {
					measure_name: measureName(v),
					column_name: v.column_name,
					data_type: isNumeric(v.data_type) ? v.data_type : 'Integer',
					aggregation: v.aggregation,
				},
			})),
		},
	}
	const result = {
		executedSQL: '',
		totalRowCount: results.value.rows.length,
		rows: results.value.rows,
		formattedRows: results.value.rows,
		columns: results.value.columns,
		columnOptions: [],
		timeTaken: results.value.time_taken,
		lastExecutedAt: new Date(),
	}
	try {
		return chartGuess.value === 'line'
			? getLineChartOptions(config as any, result as any)
			: getBarChartOptions(config as any, result as any)
	} catch (e) {
		return null
	}
})

// ---- save to workbook ----
const router = useRouter()
const showSaveDialog = ref(false)
const saveTitle = ref('')
const saving = ref(false)

function openSaveDialog() {
	saveTitle.value = selectedTable.value ? `${selectedTable.value} Exploration` : 'Exploration'
	showSaveDialog.value = true
}

async function saveExploration() {
	saving.value = true
	try {
		const result = await call('insights.api.explore.save_exploration', {
			title: saveTitle.value,
			operations: JSON.stringify(buildOperations()),
		})
		createToast({ message: __('Saved to workbooks'), variant: 'success' })
		showSaveDialog.value = false
		router.push(`/workbook/${result.workbook}/query/${result.query}`)
	} catch (e: any) {
		showErrorToast(e)
	} finally {
		saving.value = false
	}
}

const numericResultColumns = computed(() => {
	if (!results.value) return new Set<string>()
	return new Set(
		results.value.columns.filter((c: any) => isNumeric(c.type)).map((c: any) => c.name),
	)
})

function formatValue(value: any, column: string) {
	if (value == null) return ''
	if (numericResultColumns.value.has(column) && typeof value === 'number') {
		return value.toLocaleString(undefined, { maximumFractionDigits: 2 })
	}
	return String(value)
}

document.title = 'Explore | Insights'
</script>

<template>
	<header class="flex h-12 items-center justify-between border-b py-2.5 pl-5 pr-2">
		<Breadcrumbs :items="[{ label: __('Explore'), route: '/explore' }]" />
		<div class="flex items-center gap-2">
			<LoaderCircle v-if="running" class="h-4 w-4 animate-spin text-ink-gray-5" />
			<span v-if="results && results.time_taken >= 0" class="text-p-sm text-ink-gray-5">
				{{ results.rows.length }} {{ __('rows') }} · {{ results.time_taken }}s
			</span>
			<span v-else-if="results" class="text-p-sm text-ink-gray-5">
				{{ results.rows.length }} {{ __('rows (cached)') }}
			</span>
			<Button
				v-if="chartGuess"
				:variant="viewMode === 'table' ? 'outline' : 'subtle'"
				@click="viewMode = viewMode === 'table' ? 'chart' : 'table'"
			>
				<template #icon>
					<component :is="viewMode === 'table' ? BarChart3 : Table2" class="h-4 w-4" />
				</template>
			</Button>
			<Button v-if="results" variant="solid" @click="openSaveDialog()">
				<template #prefix><Save class="h-4 w-4" /></template>
				{{ __('Save') }}
			</Button>
		</div>
	</header>

	<div class="flex h-full w-full overflow-hidden">
		<!-- field list -->
		<div class="flex w-64 flex-shrink-0 flex-col gap-2 overflow-hidden border-r p-3">
			<FormControl type="select" v-model="selectedSource" :options="sourceOptions" />
			<FormControl
				v-if="selectedSource"
				type="select"
				v-model="selectedTable"
				:options="tableOptions"
			/>
			<div v-if="fields.length" class="mt-1 text-p-sm font-medium text-ink-gray-5">
				{{ __('Fields — drag into Rows, Values or Filters') }}
			</div>
			<div class="flex-1 overflow-y-auto">
				<draggable
					:list="fields"
					:group="{ name: 'fields', pull: 'clone', put: false }"
					:clone="cloneField"
					:sort="false"
					item-key="id"
				>
					<template #item="{ element }">
						<div
							class="mb-1 flex cursor-grab items-center gap-2 rounded border border-outline-gray-1 bg-surface-white px-2 py-1.5 text-p-sm text-ink-gray-8 hover:border-outline-gray-2"
						>
							<GripVertical class="h-3.5 w-3.5 flex-shrink-0 text-ink-gray-4" />
							<component
								:is="fieldIcon(element.data_type)"
								class="h-3.5 w-3.5 flex-shrink-0 text-ink-gray-5"
							/>
							<span class="truncate">{{ element.column_name }}</span>
						</div>
					</template>
				</draggable>
			</div>
		</div>

		<!-- zones + results -->
		<div class="flex flex-1 flex-col overflow-hidden">
			<div class="grid grid-cols-4 gap-3 border-b p-3">
				<!-- rows -->
				<div class="rounded border border-dashed border-outline-gray-2 p-2">
					<div class="mb-1.5 flex items-center gap-1.5 text-p-sm font-medium text-ink-gray-5">
						<Rows3 class="h-3.5 w-3.5" /> {{ __('Rows') }}
					</div>
					<draggable
						v-model="rowsZone"
						group="fields"
						item-key="id"
						class="flex min-h-8 flex-col gap-1"
					>
						<template #item="{ element }">
							<div
								class="flex items-center gap-1.5 rounded bg-surface-gray-2 px-2 py-1 text-p-sm"
							>
								<span class="truncate">{{ element.column_name }}</span>
								<FormControl
									v-if="isTemporal(element.data_type)"
									type="select"
									class="ml-auto w-24"
									v-model="element.granularity"
									:options="granularityOptions"
								/>
								<X
									class="ml-auto h-3.5 w-3.5 flex-shrink-0 cursor-pointer text-ink-gray-5"
									:class="{ 'ml-1': isTemporal(element.data_type) }"
									@click="removeFrom(rowsZone, element)"
								/>
							</div>
						</template>
					</draggable>
				</div>
				<!-- columns (pivot across) -->
				<div class="rounded border border-dashed border-outline-gray-2 p-2">
					<div class="mb-1.5 flex items-center gap-1.5 text-p-sm font-medium text-ink-gray-5">
						<Columns3 class="h-3.5 w-3.5" /> {{ __('Columns') }}
					</div>
					<draggable
						v-model="columnsZone"
						group="fields"
						item-key="id"
						class="flex min-h-8 flex-col gap-1"
					>
						<template #item="{ element }">
							<div
								class="flex items-center gap-1.5 rounded bg-surface-gray-2 px-2 py-1 text-p-sm"
							>
								<span class="truncate">{{ element.column_name }}</span>
								<FormControl
									v-if="isTemporal(element.data_type)"
									type="select"
									class="ml-auto w-24"
									v-model="element.granularity"
									:options="granularityOptions"
								/>
								<X
									class="ml-auto h-3.5 w-3.5 flex-shrink-0 cursor-pointer text-ink-gray-5"
									:class="{ 'ml-1': isTemporal(element.data_type) }"
									@click="removeFrom(columnsZone, element)"
								/>
							</div>
						</template>
					</draggable>
				</div>
				<!-- values -->
				<div class="rounded border border-dashed border-outline-gray-2 p-2">
					<div class="mb-1.5 flex items-center gap-1.5 text-p-sm font-medium text-ink-gray-5">
						<Sigma class="h-3.5 w-3.5" /> {{ __('Values') }}
					</div>
					<draggable
						v-model="valuesZone"
						group="fields"
						item-key="id"
						class="flex min-h-8 flex-col gap-1"
					>
						<template #item="{ element }">
							<div
								class="flex items-center gap-1.5 rounded bg-surface-gray-2 px-2 py-1 text-p-sm"
							>
								<span class="truncate">{{ element.column_name }}</span>
								<FormControl
									type="select"
									class="ml-auto w-32"
									v-model="element.aggregation"
									:options="aggregationOptions"
								/>
								<X
									class="ml-1 h-3.5 w-3.5 flex-shrink-0 cursor-pointer text-ink-gray-5"
									@click="removeFrom(valuesZone, element)"
								/>
							</div>
						</template>
					</draggable>
				</div>
				<!-- filters -->
				<div class="rounded border border-dashed border-outline-gray-2 p-2">
					<div class="mb-1.5 flex items-center gap-1.5 text-p-sm font-medium text-ink-gray-5">
						<SlidersHorizontal class="h-3.5 w-3.5" /> {{ __('Filters') }}
					</div>
					<draggable
						v-model="filtersZone"
						group="fields"
						item-key="id"
						class="flex min-h-8 flex-col gap-1"
					>
						<template #item="{ element }">
							<div
								class="flex items-center gap-1.5 rounded bg-surface-gray-2 px-2 py-1 text-p-sm"
							>
								<span class="max-w-24 truncate">{{ element.column_name }}</span>
								<FormControl
									type="select"
									class="w-20"
									v-model="element.operator"
									:options="operatorOptions"
								/>
								<FormControl
									:type="
										isNumeric(element.data_type)
											? 'number'
											: isTemporal(element.data_type)
											? 'date'
											: 'text'
									"
									class="flex-1"
									v-model="element.value"
								/>
								<X
									class="h-3.5 w-3.5 flex-shrink-0 cursor-pointer text-ink-gray-5"
									@click="removeFrom(filtersZone, element)"
								/>
							</div>
						</template>
					</draggable>
				</div>
			</div>

			<!-- ask the AI -->
			<div v-if="selectedSource" class="flex items-center gap-2 border-b px-3 py-2">
				<Sparkles class="h-4 w-4 flex-shrink-0 text-ink-gray-5" />
				<input
					v-model="question"
					type="text"
					class="flex-1 border-0 bg-transparent text-p-sm text-ink-gray-8 outline-none placeholder:text-ink-gray-4 focus:ring-0"
					:placeholder="
						__('Ask in plain English — e.g. total revenue by customer this year')
					"
					@keydown.enter="askAI()"
				/>
				<Button variant="subtle" :loading="asking" :disabled="!question.trim()" @click="askAI()">
					{{ __('Ask') }}
				</Button>
			</div>
			<div
				v-if="aiSQL"
				class="border-b bg-surface-gray-1 px-3 py-2 font-mono text-p-sm text-ink-gray-6"
			>
				{{ aiSQL }}
			</div>

			<!-- results -->
			<div class="flex-1 overflow-auto">
				<div
					v-if="!selectedTable && !aiSQL"
					class="flex h-full items-center justify-center text-ink-gray-5"
				>
					{{ __('Pick a data source and table, then drag fields to explore') }}
				</div>
				<div
					v-else-if="viewMode === 'chart' && chartOptions"
					class="h-full min-h-80 w-full p-4"
				>
					<BaseChart class="h-full w-full" :options="chartOptions" />
				</div>
				<table v-else-if="results" class="w-full border-collapse text-p-sm">
					<thead class="sticky top-0 bg-surface-gray-1">
						<tr>
							<th
								v-for="col in results.columns"
								:key="col.name"
								class="border-b px-3 py-2 text-left font-medium text-ink-gray-6"
								:class="{ 'text-right': numericResultColumns.has(col.name) }"
							>
								{{ col.name }}
							</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="(row, idx) in results.rows"
							:key="idx"
							class="hover:bg-surface-gray-1"
						>
							<td
								v-for="col in results.columns"
								:key="col.name"
								class="border-b border-outline-gray-1 px-3 py-1.5 text-ink-gray-8"
								:class="{
									'text-right tabular-nums': numericResultColumns.has(col.name),
								}"
							>
								{{ formatValue(row[col.name], col.name) }}
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>

	<Dialog v-model="showSaveDialog" :options="{ title: __('Save to Workbook') }">
		<template #body-content>
			<FormControl
				type="text"
				v-model="saveTitle"
				:label="__('Title')"
				autocomplete="off"
			/>
			<div class="mt-4 flex justify-end">
				<Button
					variant="solid"
					:loading="saving"
					:disabled="!saveTitle"
					@click="saveExploration()"
				>
					{{ __('Save') }}
				</Button>
			</div>
		</template>
	</Dialog>
</template>
