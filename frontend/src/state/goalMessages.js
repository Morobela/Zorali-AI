// Pure reducers for the durable-goal WS frames (capability map U1), kept out
// of Zorali.jsx so the socket handler stays a one-liner and this logic is
// unit-testable on its own.
//
// Every `goal_update` frame carries the whole goal, so the checklist attached
// to the streaming assistant message is always the newest snapshot — a
// dropped frame cannot desync the UI.

const TERMINAL_EVENTS = new Set(['goal_completed', 'goal_failed'])

export function isGoalFinished(event) {
  return TERMINAL_EVENTS.has(event)
}

/** Attach a goal snapshot to the streaming assistant message. */
export function applyGoalUpdate(messages, msg) {
  const copy = [...messages]
  const last = copy[copy.length - 1]
  if (last?.role === 'assistant' && last.streaming) {
    copy[copy.length - 1] = {
      ...last,
      goal: msg.goal,
      goalEvent: msg.event,
      streaming: !isGoalFinished(msg.event),
    }
  }
  return copy
}

/** Append streamed step output to the streaming assistant message. */
export function applyGoalToken(messages, msg) {
  const copy = [...messages]
  const last = copy[copy.length - 1]
  if (last?.role === 'assistant' && last.streaming) {
    copy[copy.length - 1] = { ...last, content: (last.content || '') + (msg.content || '') }
  }
  return copy
}
