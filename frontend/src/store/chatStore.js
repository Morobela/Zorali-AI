import { create } from 'zustand'
export const useChatStore = create((set) => ({ messages: [], add: (m) => set(s => ({messages:[...s.messages,m]})) }))
