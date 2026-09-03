import dayjs, { type Dayjs } from 'dayjs'

/**
 * 定时发布时间选择器辅助方法：
 * 禁止选择当前时刻之前的日期/时间，保证到点后服务端调度器必然能执行发布。
 */

export function disabledPastDate(time: Date): boolean {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return time.getTime() < today.getTime()
}

export function defaultScheduleTime(): string {
  const d = new Date()
  d.setSeconds(0, 0)
  d.setMilliseconds(0)
  d.setMinutes(d.getMinutes() + 1)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function isPastScheduleTime(time: string): boolean {
  return new Date(time).getTime() <= Date.now()
}

export function disabledPastHours(_role: string, comparingDate?: Dayjs): number[] {
  if (!comparingDate) return []
  const now = dayjs()
  if (!comparingDate.isSame(now, 'day')) return []
  return Array.from({ length: now.hour() }, (_, i) => i)
}

export function disabledPastMinutes(hour: number, _role: string, comparingDate?: Dayjs): number[] {
  if (!comparingDate) return []
  const now = dayjs()
  if (!comparingDate.isSame(now, 'day') || hour !== now.hour()) return []
  return Array.from({ length: now.minute() + 1 }, (_, i) => i)
}
