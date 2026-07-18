<script setup lang="ts">
import { computed, ref } from 'vue'
import Form from '../components/Form.vue'
import useDataSourceStore from './data_source'
import { B1ServiceLayerDataSource } from './data_source.types'
import { __ } from '../translation'

const show = defineModel({
	default: false,
})

const database = ref<B1ServiceLayerDataSource>({
	database_type: 'SAP B1 Service Layer',
	title: '',
	host: '',
	port: 50000,
	database_name: '',
	username: '',
	password: '',
	use_ssl: false,
})

const form = ref()
const fields = [
	{
		name: 'title',
		label: __('Title'),
		type: 'text',
		placeholder: 'SAP Business One',
		required: true,
	},
	{
		label: __('Server'),
		name: 'host',
		type: 'text',
		placeholder: 'https://b1server.company.com',
		required: true,
	},
	{
		label: __('Port'),
		name: 'port',
		type: 'number',
		placeholder: '50000',
		required: true,
		defaultValue: 50000,
	},
	{
		label: __('Company Database'),
		name: 'database_name',
		type: 'text',
		placeholder: 'SBO_COMPANYDB',
		required: true,
	},
	{
		label: __('Username'),
		name: 'username',
		type: 'text',
		placeholder: 'manager',
		required: true,
	},
	{
		label: __('Password'),
		name: 'password',
		type: 'password',
		placeholder: '**********',
		required: true,
	},
	{ label: __('Verify SSL certificate?'), name: 'use_ssl', type: 'checkbox' },
]

const sources = useDataSourceStore()

const connected = ref<boolean | null>(null)
const connectButton = computed(() => {
	const _button = {
		label: __('Connect'),
		disabled: form.value?.hasRequiredFields === false || sources.testing || sources.creating,
		loading: sources.testing,
		variant: 'subtle',
		theme: 'gray',
		onClick() {
			sources.testConnection(database.value).then((result: boolean) => {
				connected.value = Boolean(result)
			})
		},
	}

	if (sources.testing) {
		_button.label = 'Connecting...'
	} else if (connected.value) {
		_button.label = 'Connected'
		_button.variant = 'outline'
		_button.theme = 'green'
	} else if (connected.value === false) {
		_button.label = 'Failed, Retry?'
		_button.variant = 'outline'
		_button.theme = 'red'
	}

	return _button
})

const submitButton = computed(() => {
	return {
		label: __('Add Data Source'),
		disabled: form.value?.hasRequiredFields === false || !connected.value || sources.creating,
		loading: sources.creating,
		variant: connected.value ? 'solid' : 'subtle',
		onClick() {
			sources.createDataSource(database.value).then(() => {
				show.value = false
			})
		},
	}
})
</script>

<template>
	<Dialog v-model="show" :options="{ title: __('Connect to SAP B1 Service Layer') }">
		<template #body-content>
			<Form
				ref="form"
				class="flex-1"
				v-model="database"
				:fields="fields"
				:actions="[connectButton, submitButton]"
			>
			</Form>
		</template>
	</Dialog>
</template>
