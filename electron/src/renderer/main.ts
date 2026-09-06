import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { installElementPlus } from './app/element-plus'
import './assets/tailwind.css'
import { router } from './router'

const app = createApp(App)

app.use(createPinia())
app.use(router)
installElementPlus(app)

app.mount('#app')

// TTS playback is event-driven and not required to paint the initial chat UI.
// Load its bridge after the shell is mounted so audio helpers stay out of the
// critical renderer entry chunk while remaining ready for subsequent events.
void import('./audio/player')
