import React from 'react'

// Live checklist for a durable goal (capability map U1). Fed by `goal_update`
// frames, each of which carries the whole goal, so this renders straight from
// the latest snapshot and can never drift out of sync with the backend.
const STEP_ICON = {
  completed: '✓',
  running: '▶',
  failed: '✕',
  skipped: '–',
  pending: '○',
}

export default function GoalChecklist({ goal, event }) {
  if (!goal) return null
  const tasks = goal.tasks || []
  const steps = tasks.flatMap(t => t.steps || [])
  const done = steps.filter(s => s.status === 'completed').length

  return (
    <div className="goal-card">
      <div className="goal-head">
        <span className={`goal-status ${goal.status}`}>{goal.status}</span>
        <strong className="goal-objective">{goal.objective}</strong>
        <span className="goal-count">{done}/{steps.length}</span>
      </div>
      {event === 'replanned' && (
        <div className="goal-replanned">Plan revised after a failed step.</div>
      )}
      {tasks.map(task => (
        <div key={task.id} className="goal-task">
          {tasks.length > 1 && <div className="goal-task-title">{task.title}</div>}
          {(task.steps || []).map(step => (
            <div key={step.id} className={`goal-step ${step.status}`}>
              <span className="goal-step-icon">{STEP_ICON[step.status] || '○'}</span>
              <span className="goal-step-body">
                <span className="goal-step-instruction">{step.instruction}</span>
                {step.status === 'completed' && step.result && (
                  <span className="goal-step-result">{step.result}</span>
                )}
                {step.status === 'failed' && step.error && (
                  <span className="goal-step-error">{step.error}</span>
                )}
              </span>
            </div>
          ))}
        </div>
      ))}
      {goal.status === 'failed' && goal.error && (
        <div className="goal-step-error goal-error">{goal.error}</div>
      )}
    </div>
  )
}
