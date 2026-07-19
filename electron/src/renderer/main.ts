import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { installElementPlus } from './app/element-plus'
import './assets/tailwind.css'
import './audio/player'
import { router } from './router'

const app = createApp(App)

app.use(createPinia())
app.use(router)
installElementPlus(app)

app.mount('#app')
