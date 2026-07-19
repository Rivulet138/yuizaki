const SIGNATURE_WIDTH = 24
const SIGNATURE_HEIGHT = 14

export const calculateFrameDifference = (previous: Uint8Array, next: Uint8Array): number => {
  if (previous.length === 0 || previous.length !== next.length) return 1
  let difference = 0
  for (let index = 0; index < previous.length; index += 1) {
    difference += Math.abs(previous[index] - next[index])
  }
  return difference / (previous.length * 255)
}

export const computeFrameSignature = async (dataUrl: string): Promise<Uint8Array> => {
  const image = new Image()
  image.decoding = 'async'
  const loaded = new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('Unable to decode captured frame'))
  })
  image.src = dataUrl
  await loaded

  const canvas = document.createElement('canvas')
  canvas.width = SIGNATURE_WIDTH
  canvas.height = SIGNATURE_HEIGHT
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) throw new Error('Canvas 2D context is unavailable')
  context.drawImage(image, 0, 0, SIGNATURE_WIDTH, SIGNATURE_HEIGHT)
  const pixels = context.getImageData(0, 0, SIGNATURE_WIDTH, SIGNATURE_HEIGHT).data
  const signature = new Uint8Array(SIGNATURE_WIDTH * SIGNATURE_HEIGHT)
  for (let source = 0, target = 0; source < pixels.length; source += 4, target += 1) {
    signature[target] = Math.round((pixels[source] * 0.299) + (pixels[source + 1] * 0.587) + (pixels[source + 2] * 0.114))
  }
  return signature
}
