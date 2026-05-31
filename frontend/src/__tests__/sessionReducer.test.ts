import { describe, it, expect } from 'vitest'
import { sessionReducer } from '@/context/sessionReducer'
import { initialState } from '@/context/session-context'
import type { ServerEvent } from '@/types/events'

const recv = (evt: ServerEvent) =>
  sessionReducer(initialState, { type: 'RECV_EVENT', payload: evt })

describe('sessionReducer.RECV_EVENT', () => {
  it('transcript → 追加到 transcripts', () => {
    const s = recv({
      type: 'transcript', utt_id: 'u1', speaker: 'lawyer',
      text: 'hi', t_start: 0, t_end: 1, closed_by: null, is_final: true,
    })
    expect(s.transcripts).toHaveLength(1)
    expect(s.transcripts[0]).toMatchObject({ id: 'u1', text: 'hi', speaker: 'lawyer' })
  })

  it('insight.ready → 加到 insights 头部', () => {
    const s = recv({ type: 'insight.ready', id: 'ins_1', utt_id: 'u1', text: '洞察' })
    expect(s.insights).toHaveLength(1)
    expect(s.insights[0]).toMatchObject({ id: 'ins_1', uttId: 'u1', text: '洞察' })
  })

  it('analysis.proposed → 新建 pending suggestion (幂等)', () => {
    const evt: ServerEvent = {
      type: 'analysis.proposed', request_id: 'req_1', utt_id: 'u1',
      topic: 'T', rationale: 'R',
    }
    const s1 = sessionReducer(initialState, { type: 'RECV_EVENT', payload: evt })
    const s2 = sessionReducer(s1, { type: 'RECV_EVENT', payload: evt })
    expect(s1.suggestions).toHaveLength(1)
    expect(s2.suggestions).toHaveLength(1)  // 幂等
    expect(s1.suggestions[0]).toMatchObject({ status: 'pending', topic: 'T' })
  })

  it('analysis.ready → 把同 request_id 的 suggestion 改 ready', () => {
    const s1 = recv({
      type: 'analysis.proposed', request_id: 'req_1', utt_id: 'u1',
      topic: 'T', rationale: 'R',
    })
    const s2 = sessionReducer(s1, {
      type: 'RECV_EVENT',
      payload: { type: 'analysis.ready', request_id: 'req_1', utt_id: 'u1', text: '深度' },
    })
    expect(s2.suggestions[0]).toMatchObject({ status: 'ready', text: '深度' })
  })

  it('analysis.dismissed → 移除 suggestion', () => {
    const s1 = recv({
      type: 'analysis.proposed', request_id: 'req_1', utt_id: 'u1',
      topic: 'T', rationale: 'R',
    })
    const s2 = sessionReducer(s1, {
      type: 'RECV_EVENT',
      payload: { type: 'analysis.dismissed', request_id: 'req_1', reason: 'dismissed' },
    })
    expect(s2.suggestions).toHaveLength(0)
  })

  it('profile.updated → merge entries 并生成 Profile', () => {
    const s = recv({
      type: 'profile.updated',
      entries: [{ key: '姓名', value: '张三', subject: 'client' }],
    })
    expect(s.profile).not.toBeNull()
    expect(s.profile!.entries).toHaveLength(1)
  })

  it('confirm_ack ok=false → 移除对应 suggestion', () => {
    const s1 = recv({
      type: 'analysis.proposed', request_id: 'req_1', utt_id: 'u1',
      topic: 'T', rationale: 'R',
    })
    const s2 = sessionReducer(s1, {
      type: 'RECV_EVENT',
      payload: { type: 'confirm_ack', request_id: 'req_1', ok: false },
    })
    expect(s2.suggestions).toHaveLength(0)
  })

  it('pong / error → 状态不变', () => {
    const s1 = recv({ type: 'pong' })
    const s2 = recv({ type: 'error', message: 'x' })
    expect(s1).toEqual(initialState)
    expect(s2).toEqual(initialState)
  })
})
