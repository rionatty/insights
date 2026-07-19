<script setup lang="ts">
import { watchEffect } from 'vue'
import { WaterfallChartConfig, XAxis, YAxis } from '../../types/chart.types'
import { ColumnOption, DimensionOption } from '../../types/query.types'
import XAxisConfig from './XAxisConfig.vue'
import YAxisConfig from './YAxisConfig.vue'

const props = defineProps<{
	dimensions: DimensionOption[]
	columnOptions: ColumnOption[]
}>()

const config = defineModel<WaterfallChartConfig>({
	required: true,
	default: () => ({
		x_axis: {},
		y_axis: {},
	}),
})

watchEffect(() => {
	if (!config.value.x_axis) {
		config.value.x_axis = {} as XAxis
	}
	if (!config.value.y_axis) {
		config.value.y_axis = {} as YAxis
	}
})
</script>

<template>
	<XAxisConfig v-model="config.x_axis" :dimensions="props.dimensions"></XAxisConfig>
	<YAxisConfig v-model="config.y_axis" :column-options="props.columnOptions"></YAxisConfig>
</template>
