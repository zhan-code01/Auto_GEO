interface ApiResponse<T> {
  code?: number
  message?: string
  data?: T
}

export interface ClaimResult {
  task: any
  recordIds: number[]
  claimExpiresAt: string | null
  settled?: boolean
}

export interface PayloadResult {
  task: any
  publishOptions: any
  records: any[]
}

export interface ReportResult {
  settled: boolean
}

export class TaskApiClient {
  private baseUrl: string
  private token: string
  private deviceId: string
  private maxRetries = 3

  constructor(baseUrl: string, token: string, deviceId: string) {
    this.baseUrl = baseUrl.replace(/\/+$/, '')
    this.token = token
    this.deviceId = deviceId
  }

  private async fetchWithRetry(
    url: string,
    options: RequestInit = {},
    retries: number = this.maxRetries,
  ): Promise<Response> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${this.token}`,
      ...(options.headers as Record<string, string> | undefined),
    }

    for (let attempt = 1; attempt <= retries; attempt++) {
      try {
        const response = await fetch(url, { ...options, headers })

        if (response.status === 401) {
          throw new Error('Authentication failed: token expired')
        }

        if (response.status === 409) {
          return response
        }

        if (!response.ok) {
          let errorMsg = `HTTP ${response.status} ${response.statusText}`
          try {
            const body = await response.json()
            errorMsg = (body as any)?.message || (body as any)?.detail || errorMsg
          } catch {
            // keep fallback message
          }
          throw new Error(`Request failed: ${errorMsg}`)
        }

        return response
      } catch (err: any) {
        const isNetworkError =
          err?.cause?.code === 'ECONNREFUSED' ||
          err?.cause?.code === 'ECONNRESET' ||
          err?.cause?.code === 'ETIMEDOUT' ||
          err?.cause?.code === 'ENOTFOUND' ||
          err?.cause?.code === 'EAI_AGAIN' ||
          err instanceof TypeError

        if (
          err.message?.startsWith('Authentication failed') ||
          err.message?.startsWith('Request failed') ||
          (err.response && !isNetworkError)
        ) {
          throw err
        }

        if (attempt >= retries) {
          throw new Error(`Request failed after ${retries} attempts: ${err.message}`)
        }

        const delay = Math.min(1000 * Math.pow(2, attempt - 1), 8000)
        console.log(`[API] Network error, retrying in ${delay}ms (${attempt}/${retries}): ${err.message}`)
        await new Promise((resolve) => setTimeout(resolve, delay))
      }
    }

    throw new Error(`Request failed after ${retries} attempts`)
  }

  private async extractData<T>(response: Response): Promise<T> {
    const json: ApiResponse<T> | T = await response.json()
    if (json && typeof json === 'object' && 'data' in json) {
      return (json as ApiResponse<T>).data as T
    }
    return json as T
  }

  async pollTasks(platform?: string): Promise<any[]> {
    let url = `${this.baseUrl}/api/client/publish/tasks/poll?device_id=${encodeURIComponent(this.deviceId)}`
    if (platform) {
      url += `&platform=${encodeURIComponent(platform)}`
    }

    const response = await this.fetchWithRetry(url, { method: 'GET' })
    const data = await this.extractData<{ items: any[] }>(response)
    const items = data?.items || []
    if (items.length > 0) {
      console.log(`[API] Found ${items.length} publish task(s)`)
    }
    return items
  }

  async claimTask(taskId: number): Promise<ClaimResult | null> {
    const url = `${this.baseUrl}/api/client/publish/tasks/${taskId}/claim`

    console.log(`[API] Claiming task #${taskId}...`)
    const response = await this.fetchWithRetry(url, {
      method: 'POST',
      body: JSON.stringify({ device_id: this.deviceId }),
    })

    if (response.status === 409) {
      console.log(`[API] Task #${taskId} was claimed by another device`)
      return null
    }

    const data = await this.extractData<{
      task: any
      record_ids: number[]
      claim_expires_at: string | null
      settled?: boolean
    }>(response)

    console.log(`[API] Task #${taskId} claimed (${data.record_ids?.length || 0} record(s))`)
    return {
      task: data.task,
      recordIds: data.record_ids || [],
      claimExpiresAt: data.claim_expires_at,
      settled: data.settled === true,
    }
  }

  async getPayload(taskId: number): Promise<PayloadResult> {
    const url = `${this.baseUrl}/api/client/publish/tasks/${taskId}/payload?device_id=${encodeURIComponent(this.deviceId)}`

    console.log(`[API] Loading task #${taskId} payload...`)
    const response = await this.fetchWithRetry(url, { method: 'GET' })
    const data = await this.extractData<{
      task: any
      publish_options: any
      records: any[]
    }>(response)

    console.log(`[API] Task #${taskId} payload ready (${data.records?.length || 0} record(s))`)
    return {
      task: data.task,
      publishOptions: data.publish_options,
      records: data.records || [],
    }
  }

  async heartbeat(taskId: number): Promise<void> {
    const url = `${this.baseUrl}/api/client/publish/tasks/${taskId}/heartbeat`
    await this.fetchWithRetry(url, {
      method: 'POST',
      body: JSON.stringify({ device_id: this.deviceId }),
    })
    console.log(`[API] Heartbeat sent for task #${taskId}`)
  }

  async terminateTask(taskId: number): Promise<void> {
    const url = `${this.baseUrl}/api/client/publish/tasks/${taskId}/terminate`
    await this.fetchWithRetry(url, {
      method: 'POST',
      body: JSON.stringify({ device_id: this.deviceId }),
    })
  }

  async startRecord(taskId: number, recordId: number): Promise<void> {
    const url = `${this.baseUrl}/api/client/publish/tasks/${taskId}/records/${recordId}/start`
    await this.fetchWithRetry(url, {
      method: 'POST',
      body: JSON.stringify({ device_id: this.deviceId }),
    })
  }

  async reportResult(
    taskId: number,
    recordId: number,
    status: 'success' | 'failed' | 'manual_required',
    platformUrl?: string,
    errorMsg?: string,
    authStatus?: string,
  ): Promise<ReportResult> {
    const url = `${this.baseUrl}/api/client/publish/tasks/${taskId}/result`
    const body: Record<string, any> = {
      device_id: this.deviceId,
      record_id: recordId,
      status,
    }

    if (platformUrl) {
      body.platform_url = platformUrl
    }
    if (errorMsg) {
      body.error_msg = errorMsg
    }
    if (authStatus) {
      body.auth_status = authStatus
    }

    console.log(`[API] Reporting result for task #${taskId}, record #${recordId} (${status})`)
    const response = await this.fetchWithRetry(url, {
      method: 'POST',
      body: JSON.stringify(body),
    })

    const data = await this.extractData<{ task: any; settled: boolean }>(response)
    console.log(`[API] Result reported, settled=${data?.settled || false}`)
    return {
      settled: data?.settled || false,
    }
  }

  async markManualRequired(taskId: number, message: string): Promise<void> {
    const url = `${this.baseUrl}/api/client/publish/tasks/${taskId}/manual-required`

    console.log(`[API] Marking task #${taskId} as manual_required: ${message}`)
    await this.fetchWithRetry(url, {
      method: 'POST',
      body: JSON.stringify({
        device_id: this.deviceId,
        message,
      }),
    })
    console.log('[API] manual_required reported')
  }

  async resumeManualRecord(taskId: number, recordId: number): Promise<void> {
    const url = `${this.baseUrl}/api/client/publish/tasks/${taskId}/records/${recordId}/resume-manual`

    console.log(`[API] Resuming manual_required record #${recordId} for task #${taskId}`)
    await this.fetchWithRetry(url, {
      method: 'POST',
      body: JSON.stringify({
        device_id: this.deviceId,
      }),
    })
    console.log('[API] manual_required record resumed')
  }
}
