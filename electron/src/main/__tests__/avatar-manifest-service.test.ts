import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { AvatarManifestService } from '../avatar-manifest-service'

describe('AvatarManifestService', () => {
  it('does not read DisplayInfo references that resolve outside the model directory', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-avatar-root-'))
    const modelDir = path.join(root, 'avatar')
    const outsideCdi = path.join(root, 'outside.cdi3.json')
    const modelFile = path.join(modelDir, 'avatar.model3.json')

    try {
      fs.mkdirSync(modelDir, { recursive: true })
      fs.writeFileSync(outsideCdi, JSON.stringify({
        Parameters: [{ Id: 'ParamSecret', Name: 'Secret' }],
      }), 'utf8')
      fs.writeFileSync(path.join(modelDir, 'safe.cdi3.json'), JSON.stringify({
        Parameters: [{ Id: 'ParamSafe', Name: 'Safe' }],
      }), 'utf8')
      fs.writeFileSync(modelFile, JSON.stringify({
        FileReferences: {
          DisplayInfo: '../outside.cdi3.json',
        },
      }), 'utf8')

      const manifest = new AvatarManifestService(root).buildAvatarManifest(modelFile)

      expect(manifest.parameterControls.map((item) => item.id)).toEqual(['ParamSafe'])
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })

  it('uses the Live2D LipSync group parameter IDs', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-avatar-lipsync-'))
    const modelDir = path.join(root, 'avatar')
    const modelFile = path.join(modelDir, 'avatar.model3.json')

    try {
      fs.mkdirSync(modelDir, { recursive: true })
      fs.writeFileSync(modelFile, JSON.stringify({
        Groups: [{
          Target: 'Parameter',
          Name: 'LipSync',
          Ids: ['ParamMouthOpenY', 'ParamMouthOpenAlt', 'ParamMouthOpenY'],
        }],
      }), 'utf8')

      const manifest = new AvatarManifestService(root).buildAvatarManifest(modelFile)

      expect(manifest.lipSync?.parameterIds).toEqual([
        'ParamMouthOpenY',
        'ParamMouthOpenAlt',
      ])
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })

  it('falls back to ParamMouthOpenY when the Live2D LipSync group is empty', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-avatar-lipsync-fallback-'))
    const modelDir = path.join(root, 'avatar')
    const modelFile = path.join(modelDir, 'avatar.model3.json')

    try {
      fs.mkdirSync(modelDir, { recursive: true })
      fs.writeFileSync(path.join(modelDir, 'avatar.cdi3.json'), JSON.stringify({
        Parameters: [{ Id: 'ParamMouthOpenY', Name: 'Mouth Open' }],
      }), 'utf8')
      fs.writeFileSync(modelFile, JSON.stringify({
        Groups: [{ Target: 'Parameter', Name: 'LipSync', Ids: [] }],
      }), 'utf8')

      const manifest = new AvatarManifestService(root).buildAvatarManifest(modelFile)

      expect(manifest.lipSync?.parameterIds).toEqual(['ParamMouthOpenY'])
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })

  it('keeps the conventional mouth parameter fallback without a CDI file', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-avatar-lipsync-conventional-'))
    const modelDir = path.join(root, 'avatar')
    const modelFile = path.join(modelDir, 'avatar.model3.json')

    try {
      fs.mkdirSync(modelDir, { recursive: true })
      fs.writeFileSync(modelFile, JSON.stringify({ FileReferences: {} }), 'utf8')

      const manifest = new AvatarManifestService(root).buildAvatarManifest(modelFile)

      expect(manifest.lipSync?.parameterIds).toEqual(['ParamMouthOpenY'])
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })
})
