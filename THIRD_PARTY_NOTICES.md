# Third-party notices

The repository-level MIT license covers Yuizaki's original source code only.
The following bundled or downloadable components retain their own terms.

## Live2D Cubism

`electron/src/renderer/public/live2d/live2dcubismcore.min.js` is Live2D Cubism
Core and is governed by the Live2D Proprietary Software License Agreement. It
is not relicensed under MIT. Publishing or distributing an application that
uses Cubism may require a Live2D SDK Release License depending on the publisher
and use case.

Official terms:

- https://www.live2d.com/en/sdk/license/
- https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html

The Hiyori and Yumi model directories contain Live2D model data. Their model,
artwork, and character rights are separate from the Yuizaki source license.
Do not publish or redistribute them until their provenance and applicable model
terms have been recorded in this file.

## Fonts

The bundled `ZenMaruGothic-Medium.ttf` and `loli.ttf` files were copied from
`LyraVoid/Mizuki`, whose repository declares Apache License 2.0. Preserve
`electron/src/renderer/public/assets/font/MIZUKI-FONTS-NOTICE.md` with those
files and verify the upstream font-specific notices before public release.

Source: https://github.com/LyraVoid/Mizuki

## Images and character artwork

Images under `electron/src/renderer/assets/yuizaki/` and
`electron/assets/yuizaki-ribbon-icon.png` are not automatically covered by the
source-code MIT license. Keep the repository private unless the repository
owner has documented permission to redistribute every image.

## Downloaded models and services

ASR, embedding, TTS, SoulX-Singer-SVC, Hugging Face, ModelScope, Qdrant, and
other optional resources are downloaded separately. Their upstream licenses,
model cards, acceptable-use policies, and attribution requirements apply.

## Release gate

Before changing repository visibility or publishing binaries:

1. Verify and record the source and redistribution terms for every Live2D/VRM
   model, image, font, voice, and reference audio file.
2. Confirm the applicable Live2D SDK publication plan.
3. Generate a dependency license inventory for the exact release lockfiles.
4. Remove any asset whose provenance or redistribution permission is unclear.
