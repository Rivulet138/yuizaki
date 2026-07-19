export const hasVisibleAlpha = (bitmap: Buffer, alphaThreshold = 8): boolean => {
  if (bitmap.length < 4) {
    return false
  }

  for (let index = 3; index < bitmap.length; index += 4) {
    if ((bitmap[index] ?? 0) > alphaThreshold) {
      return true
    }
  }

  return false
}
