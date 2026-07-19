<script setup lang="ts">
import { Badge, Button, Dialog, FormControl, call } from 'frappe-ui'
import { CheckCircle2, LayoutTemplate } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import useDataSourceStore from '../data_source/data_source'
import { createToast } from '../helpers/toasts'
import { useTelemetry } from '../telemetry'
import { __ } from '../translation'

export type WorkbookTemplate = {
	name: string
	title: string
	description: string
	notes: string | null
	module: string
	app: string
	app_title: string
	system: string
	requires_data_source: boolean
	version: number
	has_data: boolean | null
	preview_image: string | null
	imported_workbook: number | null
	imported_version: number | null
	update_available: boolean
	customized: boolean
}

const props = defineProps<{ templates: WorkbookTemplate[] }>()
const emit = defineEmits<{ refresh: [] }>()
const show = defineModel<boolean>({ default: false })

// filter facet: the business system a template is built for (ERPNext, SAP
// Business One, ...) — derived from the templates present, so new systems
// appear in the switcher without UI changes
const selectedSystem = ref('All')
const systems = computed(() => {
	const distinct = [...new Set(props.templates.map((t) => t.system))].sort()
	return ['All', ...distinct]
})

// group by system so each system's dashboards read as one attributed section
const sections = computed(() => {
	const bySystem = new Map<string, WorkbookTemplate[]>()
	for (const template of props.templates) {
		if (selectedSystem.value !== 'All' && template.system !== selectedSystem.value) {
			continue
		}
		const group = bySystem.get(template.system) ?? []
		group.push(template)
		bySystem.set(template.system, group)
	}
	return [...bySystem.entries()]
		.map(([system, items]) => ({ system, items }))
		.sort((a, b) => a.system.localeCompare(b.system))
})

// external-source templates (e.g. SAP B1) bind to a site data source at import
const dataSourceStore = useDataSourceStore()
const sourcePickTarget = ref<WorkbookTemplate | null>(null)
const showSourcePicker = ref(false)
const selectedDataSource = ref('')
const sourceOptions = computed(() =>
	dataSourceStore.sources
		.filter((source) => !source.is_site_db)
		.map((source) => ({
			label: `${source.title} (${source.database_type})`,
			value: source.name,
		})),
)

function onImportClick(template: WorkbookTemplate) {
	if (template.requires_data_source) {
		sourcePickTarget.value = template
		selectedDataSource.value = ''
		showSourcePicker.value = true
		return
	}
	importTemplate(template)
}

function confirmSourceImport() {
	if (sourcePickTarget.value && selectedDataSource.value) {
		showSourcePicker.value = false
		importTemplate(sourcePickTarget.value, selectedDataSource.value)
	}
}

const router = useRouter()
const { capture } = useTelemetry()

// name of the template currently being imported, so only its card spins
const importing = ref<string | null>(null)

function importTemplate(template: WorkbookTemplate, dataSource?: string) {
	importing.value = template.name
	call('insights.api.templates.create_workbook_from_template', {
		template_name: template.name,
		data_source: dataSource || undefined,
	})
		.then((result: { workbook: number; dashboard: string | null }) => {
			capture('workbook_template_imported', {
				template: template.name,
				app: template.app,
				module: template.module,
			})
			createToast({ message: __('{0} imported', template.title), variant: 'success' })
			router.push(
				result.dashboard
					? `/workbook/${result.workbook}/dashboard/${result.dashboard}`
					: `/workbook/${result.workbook}`,
			)
		})
		.catch(() => {
			createToast({
				message: __('Failed to import {0}', template.title),
				variant: 'error',
			})
		})
		.finally(() => (importing.value = null))
}

function openImported(template: WorkbookTemplate) {
	// usage is tracked centrally via `workbook_template_used` on workbook load,
	// which covers every open path (list, direct URL, here) — no event needed here
	router.push(`/workbook/${template.imported_workbook}`)
}

// name of the template currently updating, so only its card's button spins
const updating = ref<string | null>(null)
// a customized copy is confirmed before its edits are overwritten
const confirmTarget = ref<WorkbookTemplate | null>(null)
const showConfirm = ref(false)

function updateTemplate(template: WorkbookTemplate) {
	if (template.customized) {
		confirmTarget.value = template
		showConfirm.value = true
		return
	}
	runUpdate(template)
}

function runUpdate(template: WorkbookTemplate) {
	showConfirm.value = false
	updating.value = template.name
	call('insights.api.templates.update_workbook_from_template', {
		template_name: template.name,
	})
		.then(() => {
			createToast({ message: __('{0} updated', template.title), variant: 'success' })
			emit('refresh')
		})
		.catch(() => {
			createToast({
				message: __('Failed to update {0}', template.title),
				variant: 'error',
			})
		})
		.finally(() => (updating.value = null))
}
</script>

<template>
	<Dialog v-model="show" :options="{ title: __('Workbook Library'), size: '4xl' }">
		<template #body-content>
			<p class="mb-5 text-p-base text-ink-gray-6 -mt-3">
				{{
					__(
						'Ready-made dashboards bundled with your installed apps. Import one to add it to your workbooks — it becomes available to everyone on your site.',
					)
				}}
			</p>
			<!-- system switcher: All / ERPNext / SAP Business One / ... -->
			<div class="mb-4 flex items-center gap-2">
				<Button
					v-for="system in systems"
					:key="system"
					:variant="selectedSystem === system ? 'solid' : 'outline'"
					@click="selectedSystem = system"
				>
					{{ system === 'All' ? __('All Systems') : system }}
				</Button>
			</div>
			<!-- cap the height so the cards scroll inside the dialog rather than
			growing the panel and scrolling the whole overlay -->
			<div class="max-h-[60vh] overflow-y-auto">
				<!-- one section per system, headed by the system's name — a single
				system just reads as one section -->
				<div v-for="section in sections" :key="section.system" class="mb-6 last:mb-0">
					<div class="mb-2.5 text-p-sm font-medium text-ink-gray-5">
						{{ section.system }}
					</div>
					<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
						<div
							v-for="template in section.items"
							:key="template.name"
							class="col-span-1 flex flex-col overflow-hidden rounded border border-outline-gray-1 bg-surface-white"
						>
							<div
								class="h-52 w-full border-b border-outline-gray-1 bg-surface-gray-1"
							>
								<img
									v-if="template.preview_image"
									:src="template.preview_image"
									:alt="template.title"
									class="h-full w-full object-cover object-top"
								/>
								<div v-else class="flex h-full w-full items-center justify-center">
									<LayoutTemplate
										class="h-8 w-8 text-ink-gray-4"
										stroke-width="1.5"
									/>
								</div>
							</div>
							<div class="flex flex-1 flex-col p-4">
								<div class="flex items-center justify-between gap-2">
									<div class="truncate text-base font-medium text-ink-gray-9">
										{{ template.title }}
									</div>
									<Badge v-if="template.module" theme="gray">
										{{ template.module }}
									</Badge>
								</div>
								<div class="mt-1.5 line-clamp-2 text-p-sm text-ink-gray-6">
									{{ template.description }}
								</div>

								<div
									v-if="template.has_data === false && !template.imported_workbook"
									class="mt-2 text-p-sm text-ink-amber-3"
								>
									{{
										__(
											'No data found on this site — dashboards may look empty.',
										)
									}}
								</div>

								<div
									v-if="template.update_available"
									class="mt-2 text-p-sm text-ink-blue-3"
								>
									{{ __('A newer version is available.') }}
								</div>

								<div class="mt-4 flex items-center gap-2">
									<template v-if="template.imported_workbook">
										<div
											class="flex items-center gap-1 text-p-sm text-ink-green-3"
										>
											<CheckCircle2 class="h-4 w-4" />
											{{ __('Imported') }}
										</div>
										<div class="ml-auto flex items-center gap-2">
											<Button
												v-if="template.update_available"
												:loading="updating === template.name"
												:disabled="!!updating"
												@click="updateTemplate(template)"
											>
												{{ __('Update') }}
											</Button>
											<Button @click="openImported(template)">
												{{ __('Open') }}
											</Button>
										</div>
									</template>
									<Button
										v-else
										class="ml-auto"
										:loading="importing === template.name"
										:disabled="!!importing"
										@click="onImportClick(template)"
									>
										{{ __('Import') }}
									</Button>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</template>
	</Dialog>

	<Dialog
		v-model="showSourcePicker"
		:options="{ title: __('Select a data source') }"
	>
		<template #body-content>
			<p class="mb-4 text-p-base text-ink-gray-6">
				{{
					__(
						'{0} runs against an external system. Choose the data source it should be connected to.',
						[sourcePickTarget?.title],
					)
				}}
			</p>
			<FormControl
				type="select"
				v-model="selectedDataSource"
				:label="__('Data Source')"
				:options="[{ label: __('Select...'), value: '' }, ...sourceOptions]"
			/>
			<div class="mt-4 flex justify-end">
				<Button
					variant="solid"
					:disabled="!selectedDataSource"
					@click="confirmSourceImport()"
				>
					{{ __('Import') }}
				</Button>
			</div>
		</template>
	</Dialog>

	<Dialog
		v-model="showConfirm"
		:options="{
			title: __('Replace your changes?'),
			message: __(
				'This dashboard has been edited on your site. Updating replaces its contents with the latest version — your changes will be lost.',
			),
			actions: [
				{
					label: __('Update'),
					variant: 'solid',
					theme: 'red',
					onClick: () => confirmTarget && runUpdate(confirmTarget),
				},
			],
		}"
	/>
</template>
