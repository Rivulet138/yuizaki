import * as PIXI from 'pixi.js'
import { Live2DSprite } from 'easy-live2d'

export function destroyCurrentModel(app: PIXI.Application | null, model: Live2DSprite | null): Live2DSprite | null {
  if (!app || !model) {
    return null
  }

  app.stage.removeChild(model)
  model.destroy()
  return null
}

export function createLive2DModel(modelPath: string): Live2DSprite {
  return new Live2DSprite({
    modelPath,
    ticker: PIXI.Ticker.shared,
    draggable: false,
  })
}
