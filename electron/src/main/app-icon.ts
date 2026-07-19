import { nativeImage, type NativeImage } from 'electron'
import fs from 'node:fs'
import path from 'node:path'

const appIconCandidates = (): string[] => [
  path.join(__dirname, '../../assets/yuizaki-ribbon-icon.png'),
  path.join(process.cwd(), 'assets/yuizaki-ribbon-icon.png'),
]

export const resolveAppIcon = (): NativeImage => {
  for (const iconPath of appIconCandidates()) {
    if (!fs.existsSync(iconPath)) {
      continue
    }

    const icon = nativeImage.createFromPath(iconPath)
    if (!icon.isEmpty()) {
      return icon
    }
  }

  return nativeImage.createEmpty()
}
