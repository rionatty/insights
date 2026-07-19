<script setup lang="ts">
import {
	AreaChart,
	BarChart3,
	BarChart4,
	BarChartHorizontal,
	BatteryMedium,
	Filter,
	Hash,
	LifeBuoy,
	LineChart,
	Map,
	ScatterChart,
	Share2,
	Table2,
	TrendingUp,
} from 'lucide-vue-next'
import { computed } from 'vue'
import { ChartType } from '../../types/chart.types'

const props = defineProps<{ chartType: ChartType }>()
const icon = computed(() => {
	switch (props.chartType) {
		case 'Bar':
			return BarChart3
		case 'Line':
			return LineChart
		case 'Row':
			return BarChartHorizontal
		case 'Bubble':
			return ScatterChart
		case 'Area':
			return AreaChart
		case 'Donut':
			return LifeBuoy
		case 'Funnel':
			return Filter
		case 'Table':
			return Table2
		case 'Number':
			return Hash
		case 'Map':
			return Map
		case 'Sankey':
			return Share2
		case 'Waterfall':
			return BarChart4
		case 'Pareto':
			return TrendingUp
		default:
			return BarChart3
	}
})
</script>

<template>
	<component :is="icon" class="h-4 w-4 text-gray-700" stroke-width="1.5" v-bind="$attrs" />
</template>
