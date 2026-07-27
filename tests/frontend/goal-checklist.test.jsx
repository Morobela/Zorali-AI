// GoalChecklist: renders a durable goal's plan from a goal_update snapshot
// (capability map U1) — step states, progress count, results and errors.
import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import GoalChecklist from '../../frontend/src/components/GoalChecklist.jsx'
import {
  applyGoalToken,
  applyGoalUpdate,
  isGoalFinished,
} from '../../frontend/src/state/goalMessages.js'

const GOAL = {
  id: 'g1',
  objective: 'Write a brief about local LLM hosting',
  status: 'running',
  error: '',
  tasks: [
    {
      id: 't1', idx: 0, title: 'Research', status: 'running', result: '', error: '',
      steps: [
        { id: 's1', idx: 0, instruction: 'find sources', status: 'completed', result: 'found three', error: '' },
        { id: 's2', idx: 1, instruction: 'read them', status: 'running', result: '', error: '' },
        { id: 's3', idx: 2, instruction: 'summarize', status: 'pending', result: '', error: '' },
      ],
    },
  ],
}

afterEach(cleanup)

describe('GoalChecklist', () => {
  it('renders nothing without a goal', () => {
    const { container } = render(<GoalChecklist goal={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows every step with its state and the progress count', () => {
    render(<GoalChecklist goal={GOAL} event="step_started" />)
    expect(screen.getByText(GOAL.objective)).toBeTruthy()
    expect(screen.getByText('1/3')).toBeTruthy()
    expect(screen.getByText('find sources')).toBeTruthy()
    expect(screen.getByText('read them')).toBeTruthy()
    expect(screen.getByText('summarize')).toBeTruthy()
    // A completed step surfaces its result.
    expect(screen.getByText('found three')).toBeTruthy()
    expect(screen.getByText('running')).toBeTruthy()
  })

  it('surfaces a failed step error and the replan notice', () => {
    const failed = {
      ...GOAL,
      tasks: [{
        ...GOAL.tasks[0],
        steps: [{ id: 's1', idx: 0, instruction: 'do the thing', status: 'failed', result: '', error: 'tool exploded' }],
      }],
    }
    render(<GoalChecklist goal={failed} event="replanned" />)
    expect(screen.getByText('tool exploded')).toBeTruthy()
    expect(screen.getByText(/Plan revised/)).toBeTruthy()
  })

  it('shows the goal-level error when the goal failed', () => {
    render(<GoalChecklist goal={{ ...GOAL, status: 'failed', error: 'no viable replan' }} />)
    expect(screen.getByText('no viable replan')).toBeTruthy()
    expect(screen.getByText('failed')).toBeTruthy()
  })

  it('shows the budget and, when paused, the reason plus a resume control', () => {
    const onResume = vi.fn()
    const paused = {
      ...GOAL,
      status: 'paused',
      cost_usd: 0.09,
      max_cost_usd: 0.1,
      pause_reason: 'Paused at $0.0900 of the $0.1000 budget (90% — the pause threshold is 80%).',
    }
    render(<GoalChecklist goal={paused} onResume={onResume} />)

    expect(screen.getByText(/\$0\.0900 \/ \$0\.1000 budget/)).toBeTruthy()
    expect(screen.getByText(/Paused at \$0\.0900/)).toBeTruthy()

    // Resuming without touching the cap sends no new cap …
    fireEvent.click(screen.getByText('Resume'))
    expect(onResume).toHaveBeenCalledWith('g1', null)

    // … and typing one passes it through.
    fireEvent.change(screen.getByLabelText('New budget cap'), { target: { value: '2.5' } })
    fireEvent.click(screen.getByText('Resume'))
    expect(onResume).toHaveBeenLastCalledWith('g1', 2.5)
  })

  it('shows the model a step ran on, with its kind when it has one', () => {
    const routed = {
      ...GOAL,
      tasks: [{
        ...GOAL.tasks[0],
        steps: [
          { id: 's1', idx: 0, instruction: 'bucket the feedback', status: 'completed', result: '', error: '', kind: 'classification', model: 'llama3.2:1b' },
          { id: 's2', idx: 1, instruction: 'write the brief', status: 'pending', result: '', error: '', kind: 'general', model: 'gpt-4o' },
        ],
      }],
    }
    render(<GoalChecklist goal={routed} />)
    expect(screen.getByText('classification · llama3.2:1b')).toBeTruthy()
    // A "general" kind adds nothing worth reading.
    expect(screen.getByText('gpt-4o')).toBeTruthy()
  })

  it('hides budget chrome for an uncapped goal that has spent nothing', () => {
    render(<GoalChecklist goal={GOAL} />)
    expect(screen.queryByText(/budget/)).toBeNull()
    expect(screen.queryByText('Resume')).toBeNull()
  })
})

describe('goal message reducers', () => {
  const streaming = [{ role: 'assistant', content: '', streaming: true }]

  it('attaches the newest goal snapshot to the streaming message', () => {
    const next = applyGoalUpdate(streaming, { goal: GOAL, event: 'step_started' })
    expect(next[0].goal).toBe(GOAL)
    expect(next[0].goalEvent).toBe('step_started')
    expect(next[0].streaming).toBe(true)
  })

  it('stops streaming on a terminal goal event', () => {
    expect(isGoalFinished('goal_completed')).toBe(true)
    expect(isGoalFinished('step_started')).toBe(false)
    const next = applyGoalUpdate(streaming, { goal: GOAL, event: 'goal_failed' })
    expect(next[0].streaming).toBe(false)
  })

  it('appends step output and leaves settled messages alone', () => {
    const next = applyGoalToken(applyGoalToken(streaming, { content: 'a' }), { content: 'b' })
    expect(next[0].content).toBe('ab')

    const settled = [{ role: 'assistant', content: 'done', streaming: false }]
    expect(applyGoalToken(settled, { content: 'x' })[0].content).toBe('done')
    expect(applyGoalUpdate(settled, { goal: GOAL, event: 'step_started' })[0].goal).toBeUndefined()
  })
})
