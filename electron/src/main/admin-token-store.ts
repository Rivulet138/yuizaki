export class AdminTokenStore {
  private summaryAdminToken = ''

  getSummaryAdminToken(): string {
    return this.summaryAdminToken
  }

  setSummaryAdminToken(token: string): { ok: boolean; hasToken: boolean } {
    this.summaryAdminToken = token.trim()
    return { ok: true, hasToken: this.summaryAdminToken.length > 0 }
  }

  clearSummaryAdminToken(): { ok: boolean } {
    this.summaryAdminToken = ''
    return { ok: true }
  }
}
