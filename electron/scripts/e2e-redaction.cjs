const { Transform } = require('node:stream')

const REDACTED = '[redacted]'

const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const createE2ERedactor = (rawToken) => {
  const tokens = (Array.isArray(rawToken) ? rawToken : [rawToken])
    .filter((token) => typeof token === 'string' && token)
  const exactSecrets = [...new Set(tokens.flatMap((token) => [token, encodeURIComponent(token)]))]
    .sort((left, right) => right.length - left.length)
    .map((secret) => new RegExp(escapeRegExp(secret), 'g'))

  const redactText = (input) => {
    let text = String(input)
    for (const secret of exactSecrets) text = text.replace(secret, REDACTED)
    return text
      .replace(/([?&](?:token|e2e_token|access_token)=)[^&#\s"'<>]*/gi, `$1${REDACTED}`)
      .replace(/(\b--token(?:=|\s+))[^\s"']+/gi, `$1${REDACTED}`)
      .replace(/(\bYUIZAKI_E2E_TOKEN\s*=\s*)[^\s,"'}]+/gi, `$1${REDACTED}`)
      .replace(/(\bX-Yuizaki-E2E-Token\b\s*[:=]\s*)[^\s,"'}]+/gi, `$1${REDACTED}`)
      .replace(/(\bAuthorization\b\s*[:=]\s*Bearer\s+)[^\s,"'}]+/gi, `$1${REDACTED}`)
      .replace(/("(?:token|e2e_token|access_token|x-yuizaki-e2e-token|authorization)"\s*:\s*")[^"]*(")/gi, `$1${REDACTED}$2`)
  }

  const redactValue = (value, seen = new WeakSet(), key = '') => {
    if (typeof value === 'string') {
      if (key.toLowerCase() === 'token_hash') return value
      return redactText(value)
    }
    if (value === null || typeof value !== 'object') return value
    if (seen.has(value)) return '[Circular]'
    seen.add(value)
    if (value instanceof Error) {
      const result = {
        name: redactText(value.name),
        message: redactText(value.message),
        stack: redactText(value.stack || value.message),
      }
      if (value.cause !== undefined) result.cause = redactValue(value.cause, seen, 'cause')
      return result
    }
    if (Array.isArray(value)) return value.map((item) => redactValue(item, seen))
    const result = {}
    for (const [entryKey, entryValue] of Object.entries(value)) {
      result[entryKey] = entryKey.toLowerCase() === 'token_hash'
        ? entryValue
        : redactValue(entryValue, seen, entryKey)
    }
    return result
  }

  const stringify = (value, space) => JSON.stringify(redactValue(value), null, space)
  return { redactText, redactValue, stringify }
}

const createRedactingTransform = (redactor) => {
  let pending = ''
  return new Transform({
    transform(chunk, _encoding, callback) {
      pending += chunk.toString('utf8')
      let newline = pending.indexOf('\n')
      while (newline >= 0) {
        this.push(`${redactor.redactText(pending.slice(0, newline))}\n`)
        pending = pending.slice(newline + 1)
        newline = pending.indexOf('\n')
      }
      callback()
    },
    flush(callback) {
      if (pending) this.push(redactor.redactText(pending))
      callback()
    },
  })
}

exports.createE2ERedactor = createE2ERedactor
exports.createRedactingTransform = createRedactingTransform
