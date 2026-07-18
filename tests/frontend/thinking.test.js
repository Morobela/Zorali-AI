// <think> extraction parser (reasoning models) — mirrors the backend
// strip_think semantics: closed blocks, multiple blocks, unclosed trailing
// block mid-stream, and pass-through for plain text.
import { describe, expect, it } from 'vitest'
import { splitThinking } from '../../frontend/src/Zorali.jsx'

describe('splitThinking', () => {
  it('passes plain text through untouched', () => {
    expect(splitThinking('just an answer')).toEqual({ thinking: '', answer: 'just an answer' })
  })

  it('separates a closed think block from the answer', () => {
    const { thinking, answer } = splitThinking('<think>weigh options</think>The answer is 4.')
    expect(thinking).toBe('weigh options')
    expect(answer).toBe('The answer is 4.')
  })

  it('joins multiple think blocks', () => {
    const { thinking, answer } = splitThinking('<think>a</think>mid<think>b</think>done')
    expect(thinking).toBe('a\nb')
    expect(answer).toBe('middone')
  })

  it('buffers an unclosed block while streaming', () => {
    const { thinking, answer } = splitThinking('<think>still going')
    expect(thinking).toBe('still going')
    expect(answer).toBe('')
  })
})
