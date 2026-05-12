import { create } from 'zustand'
export const useProjectStore = create((set) => ({ projects: [], addProject: (p) => set(s => ({projects:[...s.projects,p]})) }))
