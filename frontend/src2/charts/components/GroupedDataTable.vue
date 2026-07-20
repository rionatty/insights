<script setup lang="ts">
import { ChevronDown, ChevronRight } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { formatNumber, getShortNumber } from '../../helpers'
import { FIELDTYPES } from '../../helpers/constants'
import { Query } from '../../query/query'

const props = defineProps<{
	query: Query
	groupBy: string
	compact?: boolean
	startCollapsed?: boolean
}>()

const columns = computed(() => props.query.result.columns || [])
const rawRows = computed(() => props.query.result.rows || [])
const displayRows = computed(() => props.query.result.formattedRows || rawRows.value)

const detailColumns = computed(() => columns.value.filter((c: any) => c.name !== props.groupBy))
const isNumber = (type: string) => FIELDTYPES.NUMBER.includes(type)

type Group = { key: string; indices: number[]; sums: Record<string, number> }

const groups = computed<Group[]>(() => {
	const map = new Map<string, Group>()
	rawRows.value.forEach((row: any, idx: number) => {
		const key = String(row[props.groupBy] ?? '—')
		let group = map.get(key)
		if (!group) {
			group = { key, indices: [], sums: {} }
			map.set(key, group)
		}
		group.indices.push(idx)
		for (const col of columns.value) {
			if (!isNumber(col.type)) continue
			const val = Number(row[col.name])
			if (!isNaN(val)) group.sums[col.name] = (group.sums[col.name] || 0) + val
		}
	})
	return Array.from(map.values())
})

const collapsed = ref<Set<string>>(new Set())
watch(
	() => [props.startCollapsed, groups.value.length],
	() => {
		collapsed.value = props.startCollapsed
			? new Set(groups.value.map((g) => g.key))
			: new Set()
	},
	{ immediate: true },
)

function toggle(key: string) {
	collapsed.value.has(key) ? collapsed.value.delete(key) : collapsed.value.add(key)
	// Set mutations aren't reactive; reassign to trigger updates
	collapsed.value = new Set(collapsed.value)
}

const allCollapsed = computed(() => groups.value.length > 0 && collapsed.value.size >= groups.value.length)
function toggleAll() {
	collapsed.value = allCollapsed.value ? new Set() : new Set(groups.value.map((g) => g.key))
}

function formatSum(value: number | undefined) {
	if (value == null || isNaN(value)) return ''
	return props.compact ? getShortNumber(value, 1) : formatNumber(value)
}
</script>

<template>
	<div class="flex-1 overflow-auto">
		<table class="w-full border-separate border-spacing-0 text-sm">
			<thead class="sticky top-0 z-10 bg-white">
				<tr>
					<th
						class="cursor-pointer select-none border-b px-3 py-2 text-left font-medium text-gray-700"
						:title="allCollapsed ? 'Expand all' : 'Collapse all'"
						@click="toggleAll"
					>
						<span class="flex items-center gap-1">
							<component
								:is="allCollapsed ? ChevronRight : ChevronDown"
								class="h-3.5 w-3.5 flex-shrink-0 text-gray-500"
								stroke-width="1.5"
							/>
							{{ props.groupBy }}
						</span>
					</th>
					<th
						v-for="col in detailColumns"
						:key="col.name"
						class="border-b px-3 py-2 font-medium text-gray-700"
						:class="isNumber(col.type) ? 'text-right' : 'text-left'"
					>
						{{ col.name }}
					</th>
				</tr>
			</thead>
			<tbody>
				<template v-for="group in groups" :key="group.key">
					<tr
						class="cursor-pointer select-none bg-gray-50 hover:bg-gray-100"
						@click="toggle(group.key)"
					>
						<td class="border-b px-3 py-1.5 font-medium">
							<span class="flex items-center gap-1">
								<component
									:is="collapsed.has(group.key) ? ChevronRight : ChevronDown"
									class="h-3.5 w-3.5 flex-shrink-0 text-gray-600"
									stroke-width="1.5"
								/>
								<span class="truncate">{{ group.key }}</span>
								<span class="text-xs font-normal text-gray-500">
									({{ group.indices.length }})
								</span>
							</span>
						</td>
						<td
							v-for="col in detailColumns"
							:key="col.name"
							class="tnum border-b px-3 py-1.5 font-medium"
							:class="isNumber(col.type) ? 'text-right' : 'text-left'"
						>
							{{ isNumber(col.type) ? formatSum(group.sums[col.name]) : '' }}
						</td>
					</tr>
					<template v-if="!collapsed.has(group.key)">
						<tr v-for="idx in group.indices" :key="idx" class="hover:bg-gray-50/60">
							<td class="border-b px-3 py-1.5 pl-8 text-gray-600">
								{{ displayRows[idx]?.[props.groupBy] }}
							</td>
							<td
								v-for="col in detailColumns"
								:key="col.name"
								class="tnum border-b px-3 py-1.5"
								:class="isNumber(col.type) ? 'text-right' : 'text-left'"
							>
								{{ displayRows[idx]?.[col.name] }}
							</td>
						</tr>
					</template>
				</template>
			</tbody>
		</table>
	</div>
</template>
