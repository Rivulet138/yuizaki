import { readFileSync } from 'node:fs'
import ts from 'typescript'

// Execute selected production script declarations without mounting Element Plus.
export const panelDeclarations = (url, names) => {
  const script = readFileSync(url, 'utf8').split('<script setup lang="ts">')[1].split('</script>')[0]
  const ast = ts.createSourceFile('panel.ts', script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const declarations = ast.statements.filter(statement => {
    if (ts.isFunctionDeclaration(statement)) return Boolean(statement.name && names.includes(statement.name.text))
    return ts.isVariableStatement(statement) && statement.declarationList.declarations.some(
      declaration => ts.isIdentifier(declaration.name) && names.includes(declaration.name.text),
    )
  })
  if (declarations.length !== names.length) throw new Error(`Missing production declaration: ${names.join(', ')}`)
  return ts.transpileModule(declarations.map(node => node.getFullText(ast)).join('\n'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText
}
