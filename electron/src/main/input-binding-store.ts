import fs from 'node:fs'
import path from 'node:path'
import {
  DEFAULT_INPUT_BINDINGS,
  mergeInputBindingSettings,
  normalizeInputBindingSettings,
  type InputBindingSettings,
  type InputBindingSettingsPatch,
} from '../shared/input-bindings'

const INPUT_BINDINGS_FILENAME = 'input-bindings.json'

export class InputBindingStore {
  private readonly filePath: string
  private settings: InputBindingSettings

  constructor(storageDir: string) {
    this.filePath = path.join(storageDir, INPUT_BINDINGS_FILENAME)
    this.settings = this.load()
  }

  get(): InputBindingSettings {
    return structuredClone(this.settings)
  }

  update(patch: InputBindingSettingsPatch): InputBindingSettings {
    this.settings = mergeInputBindingSettings(this.settings, patch)
    this.save()
    return this.get()
  }

  reset(): InputBindingSettings {
    this.settings = structuredClone(DEFAULT_INPUT_BINDINGS)
    this.save()
    return this.get()
  }

  private load(): InputBindingSettings {
    try {
      return normalizeInputBindingSettings(JSON.parse(fs.readFileSync(this.filePath, 'utf8')))
    } catch {
      return structuredClone(DEFAULT_INPUT_BINDINGS)
    }
  }

  private save(): void {
    fs.mkdirSync(path.dirname(this.filePath), { recursive: true })
    const temporaryPath = `${this.filePath}.tmp`
    fs.writeFileSync(temporaryPath, `${JSON.stringify(this.settings, null, 2)}\n`, {
      encoding: 'utf8',
      mode: 0o600,
    })
    fs.renameSync(temporaryPath, this.filePath)
  }
}
