import { create } from 'zustand'
export const useUserStore = create(() => ({ user: { name: 'Owner', role: 'owner' } }))
